"""Explicit-opt-in, sequential cloud calls. No model request from an offline or CI test."""
from __future__ import annotations
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from .core import ExperimentError, dumps, loads, sha, size, parse_response, validate_state

DEFAULT = {"backend":"jev", "model":"jev-1.13.0", "endpoint":"https://api.typesafe.ai/v1/systemone",
           "key_env":"TYPESAFE_API_KEY", "input_per_million":.042, "output_per_million":0.,
           "price_verified":"2026-09-21 official models documentation", "budget_usd":.25,
           "reserve_per_call":.005,"socket_timeout_s":15,"run_deadline_s":600,"max_requests":240}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ExperimentError("redirect_blocked")

def transport(endpoint, body, key, timeout):
    req=urllib.request.Request(endpoint,data=dumps(body).encode(),method="POST",
                               headers={"Content-Type":"application/json","Authorization":"Bearer "+key,"User-Agent":"jev-test-context/0.2"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=timeout) as response:
            raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise ExperimentError("response_too_large")
        return loads(raw.decode())
    except urllib.error.HTTPError as e:
        raise ExperimentError("http_"+str(e.code)) from None
    except (urllib.error.URLError,TimeoutError,OSError,UnicodeError):
        raise ExperimentError("transport_error") from None

def validate_config(cfg):
    allowed=set(DEFAULT)|{"max_completion_tokens","cached_input_per_million","reasoning_effort"}
    if set(cfg)-allowed:raise ExperimentError("unknown_config_key_or_embedded_secret")
    if cfg.get("backend") not in {"jev","llm"}:raise ExperimentError("unknown_backend")
    endpoint={"jev":"https://api.typesafe.ai/v1/systemone","llm":"https://api.openai.com/v1/chat/completions"}[cfg["backend"]]
    if cfg.get("endpoint")!=endpoint:raise ExperimentError("unapproved_endpoint")
    if not isinstance(cfg.get("model"),str) or not cfg["model"] or cfg["model"].startswith("SET_"):raise ExperimentError("verified_model_id_required")
    if cfg["backend"]=="jev" and cfg["model"]!="jev-1.13.0":raise ExperimentError("pin_jev_version_revalidate_before_upgrade")
    for k in ("input_per_million","output_per_million","budget_usd","reserve_per_call","socket_timeout_s","run_deadline_s"):
        v=cfg.get(k)
        import math
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:raise ExperimentError("invalid_config_number")
    if cfg["budget_usd"]<=0 or cfg["reserve_per_call"]<=0 or not 1<=cfg["socket_timeout_s"]<=60 or not 1<=cfg["run_deadline_s"]<=1800:
        raise ExperimentError("invalid_budget_or_timeout")
    if not isinstance(cfg.get("max_requests"),int) or isinstance(cfg["max_requests"],bool) or not 1<=cfg["max_requests"]<=500:raise ExperimentError("invalid_request_cap")
    if not cfg.get("key_env") or not cfg.get("price_verified"):raise ExperimentError("missing_config_provenance")
    for key in ("cached_input_per_million",):
        if key in cfg:
            value=cfg[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                raise ExperimentError("invalid_cached_input_price")
    if "max_completion_tokens" in cfg:
        value=cfg["max_completion_tokens"]
        if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=8192:
            raise ExperimentError("invalid_completion_limit")
    if "reasoning_effort" in cfg and cfg["reasoning_effort"] not in {"none","low","medium","high","xhigh","max"}:
        raise ExperimentError("invalid_reasoning_effort")
    if cfg["key_env"] != {"jev":"TYPESAFE_API_KEY","llm":"OPENAI_API_KEY"}[cfg["backend"]]:raise ExperimentError("unexpected_secret_environment_name")
    return cfg

class Client:
    def __init__(self, cfg=None, *, live=False, send=transport, ledger_path=None):
        self.cfg=validate_config(dict(DEFAULT if cfg is None else cfg))
        self.live=live;self.send=send;self.started=time.monotonic();self.calls=0;self.committed=0.;self.stop=None
        self.ledger_path=Path(ledger_path) if ledger_path else None
        self.key=os.environ.get(self.cfg["key_env"],"") if live else ""
        if live and not self.key:raise ExperimentError("missing_repository_secret")
        self.persist()
    def persist(self):
        self.ledger={"calls":self.calls,"reserved_or_estimated_usd":self.committed,"stop_reason":self.stop,
                     "scope":"one manually authorized run; not a provider invoice limit","unknown_spend_reserved":self.stop in {"usage_missing","transport_error"}}
        if self.ledger_path:
            temp=self.ledger_path.with_suffix(".tmp");temp.write_text(dumps(self.ledger),encoding="utf-8");temp.replace(self.ledger_path)
    def request(self,state,qs):
        validate_state(state)
        if not qs:raise ExperimentError("empty_questions")
        payload={"model":self.cfg["model"],"state":state,"questions":qs}
        # Conservative byte guard. NOT a provider tokenizer or proof of the token limit.
        longest=max((size(q) for q in qs.values()),default=0)
        row={"status":"dry_run", "answers":None,"model":None,"usage":None,"cost_usd":None,"wall_ms":None,
             "state_sha256":sha(state),"questions_sha256":sha(qs),"request_sha256":sha(payload),"state_bytes":size(state),
             "request_bytes":size(payload),"question_count":len(qs),"error":None,"request_sent":False}
        if size(state)+longest>28000 or size(payload)>56000:
            row.update(status="blocked",error="byte_guard_no_silent_truncation");return row
        llm=self.cfg["backend"]=="llm"
        if llm:
            if any(q["type"]!="choice" for q in qs.values()):
                row.update(status="blocked",error="compact_llm_baseline_choice_only");return row
            schema={"type":"object","properties":{k:{"type":"string","enum":list(q["criteria"])} for k,q in qs.items()},"required":list(qs),"additionalProperties":False}
            body={"model":self.cfg["model"],"messages":[{"role":"system","content":"Return only the requested labels as a JSON object. No explanations."},{"role":"user","content":dumps({"state":state,"questions":qs})}],
                  "response_format":{"type":"json_schema","json_schema":{"name":"decisions","strict":True,"schema":schema}},"max_completion_tokens":self.cfg.get("max_completion_tokens",1024)}
            if "reasoning_effort" in self.cfg: body["reasoning_effort"]=self.cfg["reasoning_effort"]
            row["request_sha256"]=sha(body);row["request_bytes"]=size(body)
        else:body=payload
        if not self.live:return row
        if self.stop:row.update(status="blocked",error="backend_stopped");return row
        if self.calls>=self.cfg["max_requests"]:row.update(status="blocked",error="request_cap");return row
        if time.monotonic()-self.started>=self.cfg["run_deadline_s"]:row.update(status="blocked",error="run_deadline");return row
        # Byte-based estimate plus fixed margin; measured usage settles it. No retries or concurrent calls.
        estimate=(size(body)*self.cfg["input_per_million"]+self.cfg.get("max_completion_tokens",1024)*self.cfg["output_per_million"])/1e6
        reserve=max(self.cfg["reserve_per_call"],estimate*2)
        if self.committed+reserve>self.cfg["budget_usd"]+1e-12:
            row.update(status="blocked",error="budget_exhausted");return row
        self.committed+=reserve;self.calls+=1;self.persist()
        row["status"]="error";row["request_sent"]=True;t=time.perf_counter()
        try:
            data=self.send(self.cfg["endpoint"],body,self.key,self.cfg["socket_timeout_s"])
            usage=data.get("usage") if isinstance(data,dict) else None
            ik,ok=("prompt_tokens","completion_tokens") if llm else ("input_tokens","output_tokens")
            if isinstance(usage,dict) and all(isinstance(usage.get(k),int) and not isinstance(usage[k],bool) and usage[k]>=0 for k in (ik,ok)):
                row["usage"]={"input_tokens":usage[ik],"output_tokens":usage[ok]}
                cost=(usage[ik]*self.cfg["input_per_million"]+usage[ok]*self.cfg["output_per_million"])/1e6
                if llm:
                    details=usage.get("prompt_tokens_details",{})
                    cached=details.get("cached_tokens") if isinstance(details,dict) else None
                    row["usage"]["cached_input_tokens"]=cached
                    if cached is not None:
                        if not isinstance(cached,int) or isinstance(cached,bool) or not 0<=cached<=usage[ik]:raise ExperimentError("invalid_cached_usage")
                        cacheprice=self.cfg.get("cached_input_per_million",self.cfg["input_per_million"])
                        cost+=cached*(cacheprice-self.cfg["input_per_million"])/1e6
                row["cost_usd"]=cost;self.committed+=cost-reserve
                if cost>reserve+1e-12:self.stop="reservation_underestimated"
            else:self.stop="usage_missing"
            if llm:
                c=data["choices"][0]
                if c.get("finish_reason")!="stop" or c["message"].get("refusal"):raise ExperimentError("llm_incomplete_or_refused")
                labels=loads(c["message"]["content"])
                if not isinstance(labels,dict) or set(labels)!=set(qs) or any(v not in qs[k]["criteria"] for k,v in labels.items()):raise ExperimentError("llm_schema_error")
                row["answers"]={k:{"type":"choice","choice":v,"probabilities":None} for k,v in labels.items()}
            else:
                row["answers"]=parse_response(data,qs)
                if data["model"]!=self.cfg["model"]:raise ExperimentError("model_version_changed")
            row["model"]=data["model"];row["status"]="ok";row["error"]=self.stop
        except ExperimentError as e:
            row["error"]=str(e);self.stop=str(e);row["answers"]=None
        except Exception:
            row["error"]="unclassified_backend_failure";self.stop=row["error"];row["answers"]=None
        finally:
            row["wall_ms"]=(time.perf_counter()-t)*1000;self.persist()
        return row

def scan(root, secret=""):
    for p in Path(root).rglob("*"):
        if p.is_symlink():raise ExperimentError("artifact_symlink")
        if p.is_file():
            if p.stat().st_size>50_000_000:raise ExperimentError("artifact_too_large")
            content=p.read_bytes()
            if b"apikey_" in content or (secret and secret.encode() in content):raise ExperimentError("credential_in_artifact")

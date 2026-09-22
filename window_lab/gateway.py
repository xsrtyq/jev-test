"""Small bounded gateway for window/cache experiments."""
from __future__ import annotations
import json, os, time
from pathlib import Path
from curator.core import ExperimentError, dumps, loads, sha, size, parse_response
from evidence_lab.gateway import transport, parse_usage, scan

ENDPOINTS={"jev":("https://api.typesafe.ai/v1/systemone","jev-1.13.0","TYPESAFE_API_KEY"),
           "llm":("https://api.a2agent.me/v1/chat/completions","deepseek-v4-flash","A2AGENT_API_KEY")}
LIMITS={"jev":{"requests":40,"budget":.10,"input_price":.042,"output_price":0.0},
        "llm":{"requests":80,"budget":.50,"input_price":.14,"output_price":.28}}
DEADLINE=900

class Gateway:
    def __init__(self,out:Path,*,live_jev=False,live_llm=False,send=transport):
        self.out=Path(out); self.out.mkdir(parents=True,exist_ok=True)
        self.live={"jev":live_jev,"llm":live_llm}; self.send=send; self.start=time.monotonic(); self.stop=None
        self.keys={b:(os.environ.get(v[2],"") if self.live[b] else "") for b,v in ENDPOINTS.items()}
        if any(self.live[b] and not self.keys[b] for b in ENDPOINTS): raise ExperimentError("missing_repository_secret")
        self.counts={b:0 for b in ENDPOINTS}; self.costs={b:0.0 for b in ENDPOINTS}; self.receipts=[]
        (self.out/"requests").mkdir(exist_ok=True)
    def _record(self,row,body):
        h=sha(body); row["request_hash"]=h
        (self.out/"requests"/(h+".json")).write_text(dumps(body),encoding="utf-8")
        with (self.out/"calls.jsonl").open("a",encoding="utf-8") as f: f.write(dumps(row)+"\n")
        self.receipts.append(row); return row
    def _pre(self,backend,body,slot):
        row={"slot":slot,"backend":backend,"status":"dry_run","request_sent":False,"usage":None,"cost_usd":None,
             "wall_ms":None,"error":None,"returned_model":None,"system_fingerprint":None,"body_bytes":size(body)}
        if not self.live[backend]: return row
        if self.stop: row.update(status="blocked",error=self.stop); return row
        if time.monotonic()-self.start>=DEADLINE: self.stop="deadline"
        lim=LIMITS[backend]
        if self.counts[backend]>=lim["requests"]: self.stop="request_cap"
        if self.stop: row.update(status="blocked",error=self.stop); return row
        self.counts[backend]+=1; row.update(status="error",request_sent=True); return row
    def jev(self,state,questions,slot):
        body={"model":ENDPOINTS["jev"][1],"state":state,"questions":questions}
        row=self._pre("jev",body,slot)
        if not row["request_sent"]: return self._record(row,body)
        t=time.perf_counter()
        try:
            data=self.send(ENDPOINTS["jev"][0],body,self.keys["jev"],45)
            usage=parse_usage(data,"jev"); cost=usage["input_tokens"]*.042/1e6
            answers=parse_response(data,questions)
            if data.get("model")!=ENDPOINTS["jev"][1]: raise ExperimentError("model_mismatch")
            row.update(status="ok",usage=usage,cost_usd=cost,answers=answers,returned_model=data.get("model"))
            self.costs["jev"]+=cost
        except ExperimentError as e: row["error"]=str(e); self.stop=row["error"]
        except Exception: row["error"]="backend_protocol_error"; self.stop=row["error"]
        row["wall_ms"]=(time.perf_counter()-t)*1000
        return self._record(row,body)
    def llm(self,messages,choices,slot):
        body={"model":ENDPOINTS["llm"][1],"messages":messages,
              "response_format":{"type":"json_object"},"max_tokens":512}
        row=self._pre("llm",body,slot)
        if not row["request_sent"]: return self._record(row,body)
        t=time.perf_counter()
        try:
            data=self.send(ENDPOINTS["llm"][0],body,self.keys["llm"],45)
            usage=parse_usage(data,"llm")
            cost=(usage["input_tokens"]*.14+usage["output_tokens"]*.28)/1e6
            ch=data["choices"][0]; row["finish_reason"]=ch.get("finish_reason")
            if ch.get("finish_reason")=="length": row["status"]="censored"; row["error"]="output_limit"
            elif ch.get("finish_reason")!="stop" or ch.get("message",{}).get("refusal"): raise ExperimentError("refused_or_incomplete")
            else:
                ans=loads(ch["message"]["content"])
                if not isinstance(ans,dict) or set(ans)!={"answer"} or ans["answer"] not in choices: raise ExperimentError("invalid_answer")
                row.update(status="ok",answer=ans["answer"])
            if data.get("model")!=ENDPOINTS["llm"][1]: raise ExperimentError("model_mismatch")
            row.update(usage=usage,cost_usd=cost,returned_model=data.get("model"),system_fingerprint=data.get("system_fingerprint"))
            self.costs["llm"]+=cost
        except ExperimentError as e: row["error"]=str(e); self.stop=row["error"]
        except Exception: row["error"]="backend_protocol_error"; self.stop=row["error"]
        row["wall_ms"]=(time.perf_counter()-t)*1000
        return self._record(row,body)
    def summary(self):
        return {"counts":self.counts,"known_cost_usd":self.costs,"stop":self.stop}

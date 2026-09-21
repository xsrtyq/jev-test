"""Paired experiment: LLM alone vs the same LLM with Jev advisory information.
No arm can execute tools; every output is only a synthetic decision label.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import json
import os
import platform
import random
import statistics
from curator.client import Client,validate_config,scan
from curator.core import ExperimentError,dumps,sha
from .fixtures import dataset,DATASET_VERSION
from .core import ARMS,direct_question,signal_questions,direct_advice,signal_advice,advisory_state,decision_from_call,score_label,SIGNALS

SUITES=("quick","quality")

def make_plan(suite="quick",split="dev",seed=1729):
    if suite not in SUITES or split not in {"dev","calibration","test"}:
        raise ExperimentError("invalid_assist_plan")
    if suite=="quality":
        cases=dataset(split,seeds=(1,2))
    else:
        pool=dataset(split,seeds=(1,))
        chosen=[]
        for task_type in ("action_gate","failure_class","context_gate"):
            family=next(c["family"] for c in pool if c["task_type"]==task_type)
            chosen.extend(c for c in pool if c["family"]==family)
        cases=chosen
    random.Random(seed).shuffle(cases)
    items=[{"item_id":f"assist-{i:04d}","case":c} for i,c in enumerate(cases)]
    return {"schema":"decision-assist-plan-v0.1","suite":suite,"split":split,"seed":seed,
            "dataset_version":DATASET_VERSION,"items":items,"case_records":len(items),
            "original_groups":len({c["case"]["group_id"] for c in items}),
            "jev_requests_max":2*len(items),"llm_requests_max":4*len(items),
            "arms":list(ARMS),
            "labels":"authored provisional; translations/seeds are correlated, not independent production trials",
            "not_measured":["real tool execution","production authorization","human-validated gold","Codex subscription usage"]}

def _placeholder_direct(case):
    labels=case["labels"];p=1/len(labels)
    return {"choice":labels[0],"probabilities":{x:p for x in labels},"provider_confidence":None}

def _placeholder_signals(case):
    return {k:.5 for k in SIGNALS[case["task_type"]]}

def _call_status(call):
    return None if call is None else call.get("status")

def run_item(item,jev,llm,question_language="auto"):
    case=item["case"];dq=direct_question(case,question_language);sq=signal_questions(case,question_language)
    jdirect=jev.request(case["state"],dq)
    jsignals=jev.request(case["state"],sq)
    direct=direct_advice(jdirect);signals=signal_advice(jsignals)
    placeholder=False
    if direct is None or signals is None:
        if llm.live:
            direct=None;signals=None
        else:
            direct=_placeholder_direct(case);signals=_placeholder_signals(case);placeholder=True
    calls={};decisions={}
    for arm in ARMS:
        if arm=="jev_direct" and direct is None:
            calls[arm]=None;decisions[arm]=None;continue
        if arm=="jev_signals" and signals is None:
            calls[arm]=None;decisions[arm]=None;continue
        state=advisory_state(case,arm,direct,signals)
        call=llm.request(state,dq);calls[arm]=call;decisions[arm]=decision_from_call(call)
    row={"item_id":item["item_id"],"case_id":case["case_id"],"group_id":case["group_id"],
         "family":case["family"],"split":case["split"],"task_type":case["task_type"],"language":case["language"],
         "gold":case["gold"],"label_status":case["label_status"],"state_hash":case["state_hash"],
         "jev":{"direct_call":jdirect,"signals_call":jsignals,"direct_advice":None if placeholder else direct,
                "signal_advice":None if placeholder else signals},
         "llm_calls":calls,"decisions":decisions,"placeholder_used_for_dry_shape_only":placeholder,
         "scores":{arm:score_label(case,label) for arm,label in decisions.items()}}
    statuses=[_call_status(jdirect),_call_status(jsignals)]+[_call_status(x) for x in calls.values() if x is not None]
    if statuses and all(s=="dry_run" for s in statuses): row["status"]="dry_run"
    elif all(s=="ok" for s in statuses) and len(calls)==4 and all(calls[a] is not None for a in ARMS): row["status"]="ok"
    elif any(s=="error" for s in statuses): row["status"]="error"
    else: row["status"]="partial"
    return row

def _accuracy(rows,arm):
    vals=[r["scores"][arm] for r in rows if r["scores"].get(arm) is not None]
    return None if not vals else sum(vals)/len(vals)

def _paired(rows,arm):
    pairs=[(r["scores"].get("raw"),r["scores"].get(arm)) for r in rows
           if r["scores"].get("raw") is not None and r["scores"].get(arm) is not None]
    return {"pairs":len(pairs),
            "helped":sum(a==0 and b==1 for a,b in pairs),
            "harmed":sum(a==1 and b==0 for a,b in pairs),
            "both_correct":sum(a==1 and b==1 for a,b in pairs),
            "both_wrong":sum(a==0 and b==0 for a,b in pairs)}

def _pct(values,p):
    if not values:return None
    a=sorted(values);k=(len(a)-1)*p;i=int(k)
    return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(k-i)

def _call_stats(calls):
    sent=[x for x in calls if x and x.get("request_sent")]
    wall=[x["wall_ms"] for x in sent if x.get("wall_ms") is not None]
    return {"requests":len(sent),
            "input_tokens":sum((x.get("usage") or {}).get("input_tokens",0) for x in sent),
            "output_tokens":sum((x.get("usage") or {}).get("output_tokens",0) for x in sent),
            "reasoning_tokens":sum((x.get("usage") or {}).get("reasoning_tokens",0) for x in sent),
            "known_cost_usd":sum(x.get("cost_usd") or 0 for x in sent),
            "p50_client_ms":_pct(wall,.5),"p95_client_ms":_pct(wall,.95)}

def summarize(plan,rows,jev,llm):
    arms={a:{"usable":sum(r["scores"].get(a) is not None for r in rows),"accuracy":_accuracy(rows,a)} for a in ARMS}
    paired={a:_paired(rows,a) for a in ("neutral","jev_direct","jev_signals")}
    by_language={}
    for lang in ("zh","en","mixed"):
        rr=[r for r in rows if r["language"]==lang]
        by_language[lang]={a:_accuracy(rr,a) for a in ARMS}
    by_task={}
    for task in ("action_gate","failure_class","context_gate"):
        rr=[r for r in rows if r["task_type"]==task]
        by_task[task]={a:_accuracy(rr,a) for a in ARMS}
    jev_direct=[int(r["jev"]["direct_advice"]["choice"]==r["gold"]) for r in rows if r["jev"]["direct_advice"]]
    arm_usage={a:_call_stats([r["llm_calls"].get(a) for r in rows]) for a in ARMS}
    pipeline_usage={
        "raw":dict(arm_usage["raw"]),
        "neutral":dict(arm_usage["neutral"]),
        "jev_direct":_call_stats([x for r in rows for x in (r["jev"]["direct_call"],r["llm_calls"].get("jev_direct"))]),
        "jev_signals":_call_stats([x for r in rows for x in (r["jev"]["signals_call"],r["llm_calls"].get("jev_signals"))])
    }
    def backend_stats(client,which):
        calls=[]
        for r in rows:
            if which=="jev": calls += [r["jev"]["direct_call"],r["jev"]["signals_call"]]
            else: calls += [x for x in r["llm_calls"].values() if x is not None]
        sent=[x for x in calls if x and x.get("request_sent")]
        return {"requests":len(sent),"known_cost_usd":sum(x.get("cost_usd") or 0 for x in sent),
                "input_tokens":sum((x.get("usage") or {}).get("input_tokens",0) for x in sent),
                "output_tokens":sum((x.get("usage") or {}).get("output_tokens",0) for x in sent),
                "model":client.cfg["model"],"provider_label":client.cfg.get("provider_label"),"upstream_model_verified":client.cfg.get("upstream_model_verified"),"stop_reason":client.stop}
    return {"schema":"decision-assist-summary-v0.1","suite":plan["suite"],"split":plan["split"],
            "execution":"live_both" if jev.live and llm.live else "jev_only" if jev.live else "offline",
            "planned_records":len(plan["items"]),"completed_records":len(rows),"statuses":dict(Counter(r["status"] for r in rows)),
            "arms":arms,"paired_vs_raw":paired,"by_language":by_language,"by_task":by_task,
            "llm_arm_usage":arm_usage,"pipeline_usage":pipeline_usage,
            "jev_direct_diagnostic_accuracy":None if not jev_direct else sum(jev_direct)/len(jev_direct),
            "jev_backend":backend_stats(jev,"jev"),"llm_backend":backend_stats(llm,"llm"),
            "caveats":["Synthetic authored labels are provisional and correlated across languages/seeds.",
                       "Jev advice is explicitly untrusted; this benchmark measures label assistance, not authorization.",
                       "A neutral-advisory arm controls for extra framing but not every prompt-length effect.",
                       "No action is executed and no production safety boundary is delegated to either model.",
                       "Use paired helped/harmed counts; accuracy alone can hide anchoring harm."]}

def report(summary):
    fmt=lambda x:"unknown" if x is None else f"{x:.3f}"
    lines=["# Jev -> LLM decision assistance report","",
           f"execution={summary['execution']}; suite={summary['suite']} split={summary['split']}.","",
           "|arm|usable|accuracy|","|---|---:|---:|"]
    for arm,v in summary["arms"].items():
        lines.append(f"|{arm}|{v['usable']}|{fmt(v['accuracy'])}|")
    lines += ["","## Paired changes vs raw LLM","",
              "|arm|pairs|helped|harmed|both correct|both wrong|","|---|---:|---:|---:|---:|---:|"]
    for arm,v in summary["paired_vs_raw"].items():
        lines.append(f"|{arm}|{v['pairs']}|{v['helped']}|{v['harmed']}|{v['both_correct']}|{v['both_wrong']}|")
    lines += ["","## Per-arm usage (relay/model only)","",
              "|arm|input|output|reasoning|cost USD|p50 ms|p95 ms|","|---|---:|---:|---:|---:|---:|---:|"]
    for arm,v in summary["llm_arm_usage"].items():
        lines.append(f"|{arm}|{v['input_tokens']}|{v['output_tokens']}|{v['reasoning_tokens']}|{v['known_cost_usd']:.6f}|{fmt(v['p50_client_ms'])}|{fmt(v['p95_client_ms'])}|")
    lines += ["","## End-to-end advisory pipeline usage","",
              "|arm|cost USD|p50 ms|p95 ms|","|---|---:|---:|---:|"]
    for arm,v in summary["pipeline_usage"].items():
        lines.append(f"|{arm}|{v['known_cost_usd']:.6f}|{fmt(v['p50_client_ms'])}|{fmt(v['p95_client_ms'])}|")
    lines += ["",f"Jev direct diagnostic accuracy: {fmt(summary['jev_direct_diagnostic_accuracy'])}.",
              f"Jev requests/cost: {summary['jev_backend']['requests']} / USD {summary['jev_backend']['known_cost_usd']:.6f}.",
              f"LLM requests/cost: {summary['llm_backend']['requests']} / USD {summary['llm_backend']['known_cost_usd']:.6f}.",
              "","## Boundaries",""]+["- "+x for x in summary["caveats"]]
    return "\n".join(lines)+"\n"

def execute(plan,out,jev_cfg,llm_cfg,live_jev=False,live_llm=False,question_language="auto",jev_send=None,llm_send=None):
    out=Path(out)
    if out.exists(): raise ExperimentError("output_exists")
    if live_llm and not live_jev: raise ExperimentError("paid_llm_requires_real_or_frozen_jev_advice")
    if question_language not in {"auto","zh","en"}: raise ExperimentError("invalid_question_language")
    jev_cfg=validate_config(dict(jev_cfg));llm_cfg=validate_config(dict(llm_cfg))
    if jev_cfg["backend"]!="jev" or llm_cfg["backend"] not in {"llm","openai_compatible"}: raise ExperimentError("assist_backend_mismatch")
    if plan["jev_requests_max"]>jev_cfg["max_requests"] or plan["llm_requests_max"]>llm_cfg["max_requests"]:
        raise ExperimentError("assist_plan_exceeds_request_cap")
    out.mkdir(parents=True)
    (out/"plan.json").write_text(dumps(plan),encoding="utf-8")
    (out/"jev-config.json").write_text(dumps(jev_cfg),encoding="utf-8")
    (out/"llm-config.json").write_text(dumps(llm_cfg),encoding="utf-8")
    manifest={"commit":os.environ.get("GITHUB_SHA"),"runtime":{"python":platform.python_version(),"platform":platform.platform()},
              "plan_sha256":sha(plan),"live_jev":live_jev,"live_llm":live_llm,"question_language":question_language}
    (out/"manifest.json").write_text(dumps(manifest),encoding="utf-8")
    jk={"cfg":jev_cfg,"live":live_jev,"ledger_path":out/"jev-ledger.json"}
    lk={"cfg":llm_cfg,"live":live_llm,"ledger_path":out/"llm-ledger.json"}
    if jev_send is not None: jk["send"]=jev_send
    if llm_send is not None: lk["send"]=llm_send
    jev=Client(**jk);llm=Client(**lk);rows=[]
    with (out/"results.jsonl").open("x",encoding="utf-8") as fh:
        for item in plan["items"]:
            row=run_item(item,jev,llm,question_language);rows.append(row);fh.write(dumps(row)+"\n");fh.flush()
            if (live_jev and jev.stop) or (live_llm and llm.stop): break
    summary=summarize(plan,rows,jev,llm)
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (out/"report.md").write_text(report(summary),encoding="utf-8")
    failures=[r for r in rows if r["status"] in {"error","partial"} or
              any(r["scores"].get(a)==0 and r["scores"].get("raw")==1 for a in ("jev_direct","jev_signals"))]
    (out/"failures.jsonl").write_text("".join(dumps(r)+"\n" for r in failures),encoding="utf-8")
    scan(out,jev.key);scan(out,llm.key)
    return summary

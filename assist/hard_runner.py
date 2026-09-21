"""Hard decision-assist runner with balanced arm order, repeated downstream calls, and known-wrong advice stress.
Jev is called once per case (direct + signals) and reused across two identical-input downstream repeats.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from pathlib import Path
import json
import os
import platform
import statistics
from curator.client import Client,validate_config,scan
from curator.core import ExperimentError,dumps,sha
from .hard_fixtures import dataset,DATASET_VERSION
from .core import HARD_ARMS,direct_question,signal_questions,direct_advice,signal_advice,advisory_state,decision_from_call,score_label,known_wrong_direct

REPEATS=2

def _rotated_orders(index):
    arms=list(HARD_ARMS);n=len(arms)
    shifts=(index % n,(index+2) % n)
    return [arms[s:]+arms[:s] for s in shifts]

def make_plan(split="dev",seed=1729):
    if split not in {"dev","calibration","test"}: raise ExperimentError("invalid_hard_assist_split")
    cases=dataset(split)
    # Fixtures already deterministic; plan order is a stable hash sort to avoid hand-picked sequencing.
    cases=sorted(cases,key=lambda c:sha({"seed":seed,"case_id":c["case_id"]}))
    items=[]
    for i,case in enumerate(cases):
        items.append({"item_id":f"hard-assist-{i:04d}","case":case,"arm_orders":_rotated_orders(i),"repeats":REPEATS})
    return {"schema":"decision-assist-hard-plan-v0.2","suite":"hard","split":split,"seed":seed,
            "dataset_version":DATASET_VERSION,"items":items,"case_records":len(items),
            "original_groups":len({x["case"]["group_id"] for x in items}),
            "arms":list(HARD_ARMS),"repeats":REPEATS,
            "jev_requests_max":2*len(items),"llm_requests_max":len(items)*REPEATS*len(HARD_ARMS),
            "arm_order":"deterministic cyclic counterbalancing frozen in plan",
            "wrong_advice":"synthetic gold-aware stressor; never counted as Jev output",
            "labels":"authored provisional; language variants are correlated, not independent production trials"}

def _status(call):
    return None if call is None else call.get("status")

def run_item(item,jev,llm,question_language="auto"):
    case=item["case"];dq=direct_question(case,question_language);sq=signal_questions(case,question_language)
    jdirect=jev.request(case["state"],dq)
    jsignals=jev.request(case["state"],sq)
    direct=direct_advice(jdirect);signals=signal_advice(jsignals)
    wrong=known_wrong_direct(case)
    trials=[]
    if llm.live and (direct is None or signals is None):
        return {"item_id":item["item_id"],"case_id":case["case_id"],"group_id":case["group_id"],
                "family":case["family"],"language":case["language"],"task_type":case["task_type"],"gold":case["gold"],
                "jev":{"direct_call":jdirect,"signals_call":jsignals,"direct_advice":direct,"signal_advice":signals},
                "wrong_advice":wrong,"trials":[],"status":"partial","label_status":case["label_status"]}
    for repeat,order in enumerate(item["arm_orders"]):
        calls={};decisions={};scores={};positions={}
        for position,arm in enumerate(order,1):
            if arm=="jev_direct": state=advisory_state(case,arm,direct=direct)
            elif arm=="jev_signals": state=advisory_state(case,arm,signals=signals)
            elif arm=="wrong_direct": state=advisory_state(case,arm,direct=wrong)
            else: state=advisory_state(case,arm)
            call=llm.request(state,dq);calls[arm]=call;positions[arm]=position
            label=decision_from_call(call);decisions[arm]=label;scores[arm]=score_label(case,label)
            if call.get("status") in {"error","blocked"}: break
        trials.append({"repeat":repeat,"order":order,"positions":positions,"calls":calls,
                       "decisions":decisions,"scores":scores})
        if llm.stop: break
    statuses=[_status(jdirect),_status(jsignals)]+[_status(call) for t in trials for call in t["calls"].values()]
    expected=REPEATS*len(HARD_ARMS)+2
    if len(statuses)==expected and all(s=="ok" for s in statuses): status="ok"
    elif statuses and all(s=="dry_run" for s in statuses): status="dry_run"
    elif any(s=="error" for s in statuses): status="error"
    else: status="partial"
    return {"item_id":item["item_id"],"case_id":case["case_id"],"group_id":case["group_id"],
            "family":case["family"],"split":case["split"],"language":case["language"],"task_type":case["task_type"],
            "gold":case["gold"],"label_status":case["label_status"],"state_hash":case["state_hash"],
            "jev":{"direct_call":jdirect,"signals_call":jsignals,"direct_advice":direct,"signal_advice":signals},
            "wrong_advice":wrong,"trials":trials,"status":status}

def _records(rows,arm):
    out=[]
    for row in rows:
        for trial in row["trials"]:
            if arm in trial["scores"] and trial["scores"][arm] is not None:
                out.append((row,trial,trial["scores"][arm],trial["calls"][arm]))
    return out

def _acc(rows,arm):
    rs=_records(rows,arm);return None if not rs else sum(x[2] for x in rs)/len(rs)

def _paired(rows,arm):
    pairs=[]
    for row in rows:
        for trial in row["trials"]:
            a=trial["scores"].get("raw");b=trial["scores"].get(arm)
            if a is not None and b is not None:pairs.append((a,b))
    return {"pairs":len(pairs),"helped":sum(a==0 and b==1 for a,b in pairs),
            "harmed":sum(a==1 and b==0 for a,b in pairs),
            "both_correct":sum(a==1 and b==1 for a,b in pairs),
            "both_wrong":sum(a==0 and b==0 for a,b in pairs)}

def _repeat_flips(rows,arm):
    usable=flips=0
    for row in rows:
        if len(row["trials"])<2:continue
        a=row["trials"][0]["decisions"].get(arm);b=row["trials"][1]["decisions"].get(arm)
        if a is not None and b is not None:
            usable+=1;flips+=a!=b
    return {"cases":usable,"flips":flips,"rate":flips/usable if usable else None}

def _pct(xs,p):
    if not xs:return None
    a=sorted(xs);k=(len(a)-1)*p;i=int(k)
    return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(k-i)

def _call_stats(calls):
    sent=[c for c in calls if c and c.get("request_sent")]
    wall=[c["wall_ms"] for c in sent if c.get("wall_ms") is not None]
    return {"requests":len(sent),"input_tokens":sum((c.get("usage") or {}).get("input_tokens",0) for c in sent),
            "output_tokens":sum((c.get("usage") or {}).get("output_tokens",0) for c in sent),
            "reasoning_tokens":sum((c.get("usage") or {}).get("reasoning_tokens",0) for c in sent),
            "known_cost_usd":sum(c.get("cost_usd") or 0 for c in sent),
            "p50_client_ms":_pct(wall,.5),"p95_client_ms":_pct(wall,.95)}

def summarize(plan,rows,jev,llm):
    arms={arm:{"usable":len(_records(rows,arm)),"accuracy":_acc(rows,arm),
               "repeat_consistency":_repeat_flips(rows,arm)} for arm in HARD_ARMS}
    paired={arm:_paired(rows,arm) for arm in HARD_ARMS if arm!="raw"}
    by_language={lang:{arm:_acc([r for r in rows if r["language"]==lang],arm) for arm in HARD_ARMS}
                 for lang in ("zh","en","mixed")}
    by_task={task:{arm:_acc([r for r in rows if r["task_type"]==task],arm) for arm in HARD_ARMS}
             for task in ("action_gate","failure_class","context_gate")}
    position=defaultdict(list)
    for row in rows:
        for trial in row["trials"]:
            for arm,pos in trial["positions"].items():
                score=trial["scores"].get(arm)
                call=trial["calls"].get(arm)
                if score is not None:position[(arm,pos)].append((score,call))
    position_diag={}
    for (arm,pos),vals in position.items():
        position_diag[f"{arm}@{pos}"]={"n":len(vals),"accuracy":sum(x[0] for x in vals)/len(vals),
                                      "reasoning_tokens":sum((x[1].get("usage") or {}).get("reasoning_tokens",0) for x in vals)}
    llm_usage={arm:_call_stats([x[3] for x in _records(rows,arm)]) for arm in HARD_ARMS}
    jev_direct_calls=[r["jev"]["direct_call"] for r in rows];jev_signal_calls=[r["jev"]["signals_call"] for r in rows]
    pipeline_usage={
        "raw":dict(llm_usage["raw"]),"neutral":dict(llm_usage["neutral"]),
        "wrong_direct":dict(llm_usage["wrong_direct"]),
        "jev_direct":_call_stats(jev_direct_calls+[x[3] for x in _records(rows,"jev_direct")]),
        "jev_signals":_call_stats(jev_signal_calls+[x[3] for x in _records(rows,"jev_signals")])
    }
    wrong_followed=wrong_harm=raw_correct_pairs=0
    for row in rows:
        wrong_label=row["wrong_advice"]["choice"]
        for trial in row["trials"]:
            wd=trial["decisions"].get("wrong_direct");raw=trial["scores"].get("raw");wscore=trial["scores"].get("wrong_direct")
            if wd is not None:
                wrong_followed+=wd==wrong_label
            if raw is not None and wscore is not None:
                raw_correct_pairs+=raw==1
                wrong_harm+=raw==1 and wscore==0
    jev_direct_correct=[int(r["jev"]["direct_advice"]["choice"]==r["gold"]) for r in rows if r["jev"]["direct_advice"]]
    return {"schema":"decision-assist-hard-summary-v0.2","suite":"hard","split":plan["split"],
            "execution":"live_both" if jev.live and llm.live else "offline",
            "planned_records":len(plan["items"]),"completed_records":len(rows),"statuses":dict(Counter(r["status"] for r in rows)),
            "arms":arms,"paired_vs_raw":paired,"by_language":by_language,"by_task":by_task,
            "wrong_advice":{"followed":wrong_followed,"trials":sum(len(r["trials"]) for r in rows),
                            "raw_correct_pairs":raw_correct_pairs,"harmed_when_raw_correct":wrong_harm},
            "position_diagnostics":position_diag,"llm_arm_usage":llm_usage,"pipeline_usage":pipeline_usage,
            "jev_direct_diagnostic_accuracy":sum(jev_direct_correct)/len(jev_direct_correct) if jev_direct_correct else None,
            "jev_backend":_call_stats(jev_direct_calls+jev_signal_calls),
            "llm_backend":_call_stats([call for r in rows for t in r["trials"] for call in t["calls"].values()]),
            "caveats":["Hard labels are authored/provisional and language variants are correlated.",
                       "Repeated calls measure stochastic stability, not additional independent cases.",
                       "Known-wrong advice is a synthetic gold-aware stressor and is never counted as Jev performance.",
                       "Balanced order is diagnostic; the sample is too small for a causal order-effect estimate.",
                       "No external action is executed and model advice has no authorization authority."]}

def report(s):
    fmt=lambda x:"unknown" if x is None else f"{x:.3f}"
    lines=["# Hard Jev -> LLM decision assistance report","",
           f"execution={s['execution']} split={s['split']}.","",
           "|arm|usable trials|accuracy|repeat flips|","|---|---:|---:|---:|"]
    for arm,v in s["arms"].items():
        lines.append(f"|{arm}|{v['usable']}|{fmt(v['accuracy'])}|{v['repeat_consistency']['flips']}/{v['repeat_consistency']['cases']}|")
    lines+=["","## Paired vs raw","",
            "|arm|pairs|helped|harmed|both correct|both wrong|","|---|---:|---:|---:|---:|---:|"]
    for arm,v in s["paired_vs_raw"].items():
        lines.append(f"|{arm}|{v['pairs']}|{v['helped']}|{v['harmed']}|{v['both_correct']}|{v['both_wrong']}|")
    w=s["wrong_advice"]
    lines+=["",f"Known-wrong advice followed: {w['followed']}/{w['trials']}; harmed when raw was correct: {w['harmed_when_raw_correct']}/{w['raw_correct_pairs']}.",
            "","## Per-arm downstream usage","",
            "|arm|input|output|reasoning|cost USD|p50 ms|","|---|---:|---:|---:|---:|---:|"]
    for arm,v in s["llm_arm_usage"].items():
        lines.append(f"|{arm}|{v['input_tokens']}|{v['output_tokens']}|{v['reasoning_tokens']}|{v['known_cost_usd']:.6f}|{fmt(v['p50_client_ms'])}|")
    lines+=["","## Boundaries",""]+["- "+x for x in s["caveats"]]
    return "\n".join(lines)+"\n"

def execute(plan,out,jev_cfg,llm_cfg,live_jev=False,live_llm=False,question_language="auto",jev_send=None,llm_send=None):
    out=Path(out)
    if out.exists():raise ExperimentError("output_exists")
    if live_llm and not live_jev:raise ExperimentError("paid_llm_requires_real_jev")
    jev_cfg=validate_config(dict(jev_cfg));llm_cfg=validate_config(dict(llm_cfg))
    if jev_cfg["backend"]!="jev" or llm_cfg["backend"] not in {"llm","openai_compatible"}:raise ExperimentError("assist_backend_mismatch")
    if plan["jev_requests_max"]>jev_cfg["max_requests"] or plan["llm_requests_max"]>llm_cfg["max_requests"]:raise ExperimentError("assist_plan_exceeds_request_cap")
    out.mkdir(parents=True)
    (out/"plan.json").write_text(dumps(plan),encoding="utf-8")
    (out/"jev-config.json").write_text(dumps(jev_cfg),encoding="utf-8")
    (out/"llm-config.json").write_text(dumps(llm_cfg),encoding="utf-8")
    (out/"manifest.json").write_text(dumps({"commit":os.environ.get("GITHUB_SHA"),"python":platform.python_version(),
                                             "plan_sha256":sha(plan),"live_jev":live_jev,"live_llm":live_llm,
                                             "question_language":question_language}),encoding="utf-8")
    jk={"cfg":jev_cfg,"live":live_jev,"ledger_path":out/"jev-ledger.json"};lk={"cfg":llm_cfg,"live":live_llm,"ledger_path":out/"llm-ledger.json"}
    if jev_send is not None:jk["send"]=jev_send
    if llm_send is not None:lk["send"]=llm_send
    jev=Client(**jk);llm=Client(**lk);rows=[]
    with (out/"results.jsonl").open("x",encoding="utf-8") as fh:
        for item in plan["items"]:
            row=run_item(item,jev,llm,question_language);rows.append(row);fh.write(dumps(row)+"\n");fh.flush()
            if (live_jev and jev.stop) or (live_llm and llm.stop):break
    s=summarize(plan,rows,jev,llm)
    (out/"summary.json").write_text(json.dumps(s,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (out/"report.md").write_text(report(s),encoding="utf-8")
    failures=[r for r in rows if r["status"] in {"error","partial"} or any(
        t["scores"].get("raw")==1 and any(t["scores"].get(a)==0 for a in ("jev_direct","jev_signals","wrong_direct"))
        for t in r["trials"])]
    (out/"failures.jsonl").write_text("".join(dumps(r)+"\n" for r in failures),encoding="utf-8")
    scan(out,jev.key);scan(out,llm.key)
    return s

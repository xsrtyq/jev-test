"""Reproducible plans, primary evidence experiments and bounded evolving-history replay."""
from __future__ import annotations
from collections import defaultdict, Counter
from copy import deepcopy
import random
import statistics
import time
from pathlib import Path
from .core import *
from .fixtures import dataset, episode, TEMPLATES, SPLIT, perturb, DATASET_VERSION
from .client import Client, DEFAULT, scan, validate_config
from . import retrieval as retrieval_lab

SUITES=("quick","quality","robustness","retrieval","scaling","fanout","replay")

def make_plan(suite="quick",split="dev",seed=1729,steps=20,backend="jev"):
    if suite not in SUITES or split not in {"dev","calibration","test"} or steps not in {10,20,50}:
        raise ExperimentError("invalid_plan_options")
    pool=dataset(split,seeds=(1,))[:6]
    items=[]
    def add(ep,method="choice",variant="base",repeat=0,batch=0):
        items.append({"episode":ep,"method":method,"variant":variant,"repeat":repeat,"batch_questions":batch})
    methods=("choice",) if backend=="llm" else METHODS
    if suite in {"quick","quality"}:
        for ep in pool if suite=="quick" else dataset(split):
            for method in methods:add(ep,method)
    elif suite=="robustness":
        for ep in pool:
            for v in ("base","repeat","reverse_options","reverse_blocks","injection","short_view"):
                add(perturb(ep,v),variant=v,repeat=int(v=="repeat"))
    elif suite=="retrieval":
        for ep in dataset(split,seeds=(1,)): add(ep,"retrieval")
    elif suite=="scaling":
        for ep in pool:
            template=next(t for t in TEMPLATES if t[0]==ep["family"])
            for n in (0,2000,8000,16000):
                for position in ("first","last"):
                    add(episode(template,ep["seed"],ep["language"],n,position))
    elif suite=="fanout":
        for r in (0,1):
            for batch in (1,4,13):add(deepcopy(pool[0]),repeat=r,batch=batch)
    elif suite=="replay":
        for ep in pool:add(ep,"choice" if backend=="llm" else "signals")
    random.Random(seed).shuffle(items)
    calls=0
    for i,it in enumerate(items):
        ep=it["episode"]
        if suite=="retrieval":
            s=deepcopy(ep["state"]);s["query"]=ep["later_query"]
            q,_=retrieval_lab.questions(s,"en" if ep["language"]=="en" else "zh")
        else:
            q,_=questions(ep["state"],it["method"],"en" if ep["language"]=="en" else "zh")
        batches=(len(q)+it["batch_questions"]-1)//it["batch_questions"] if it["batch_questions"] else 1
        calls+=len(checkpoints(steps)) if suite=="replay" else batches
        it["item_id"]=f"item-{i:04d}"
    return {"schema":"context-plan-v0.2","suite":suite,"split":split,"seed":seed,"steps":steps,"backend":backend,
            "dataset_version":DATASET_VERSION,"items":items,"max_model_requests":calls,
            "scenario_groups":len({x['episode']['group_id'] for x in items}),
            "template_families":len({x['episode']['family'] for x in items}),
            "condition_records":len(items),"order":"seeded interleaving; sequential HTTP",
            "labels":"authored provisional; not independent human annotation",
            "limits":{"budget_usd":.25,"max_requests":240,"run_deadline_s":600},
            "not_measured":["downstream LLM task success","native Codex KV or prompt cache","local neural models","human-validated production accuracy"]}

def checkpoints(steps):
    return sorted(set([s for s in range(5,steps+1,5)]+[steps-2,steps]))

def baseline_results(state,budget,gold):
    result={}
    for mode in ("keep_all","recency","lexical","equal_score"):
        sel=select(state,mode=mode,budget=budget)
        result[mode]={"selection":sel,"metrics":score(sel,gold)}
    return result

def call_item(item,client,budget=3000,question_language="auto"):
    ep=item["episode"];state=deepcopy(ep["state"]);model_state=deepcopy(state)
    language="en" if question_language=="en" or (question_language=="auto" and ep["language"]=="en") else "zh"
    if item["variant"]=="short_view":
        for b in model_state["blocks"]:b["text"]=b["text"][:120]
    qs,mapping=questions(model_state,item["method"],language,item["variant"]=="reverse_options")
    n=item["batch_questions"] or len(qs);parts=list(qs.items());calls=[];answers={}
    for start in range(0,len(parts),n):
        call=client.request(model_state,dict(parts[start:start+n]));calls.append(call)
        if call["status"]=="ok":answers.update(call["answers"])
        elif call["status"] in {"blocked","error"}:break
    status="ok" if len(answers)==len(qs) else "dry_run" if all(c["status"]=="dry_run" for c in calls) else "error"
    base=baseline_results(state,budget,ep["gold"])
    row={"item_id":item["item_id"],"episode_id":ep["episode_id"],"group_id":ep["group_id"],"family":ep["family"],"language":ep["language"],"split":ep["split"],
         "method":item["method"],"variant":item["variant"],"repeat":item["repeat"],"batch_questions":item["batch_questions"],
         "condition":ep["condition"],"status":status,"calls":calls,"input_state":model_state,"question_template":qs,"mapping":mapping,
         "reference_input_state":state,"gold":ep["gold"],"label_status":ep["label_status"],"baselines":base,"model_result":None}
    if status=="ok":
        advice=signals_from_answers(answers,mapping)
        chosen=select(state,advice,mode="model",budget=budget,expected_revision=sha(state))
        row["model_result"]={"advice":advice,"selection":chosen,"metrics":score(chosen,ep["gold"],advice)}
        row["budget_sweep_no_extra_api"]={}
        for cap in (2400,3000,3800):
            sweep=select(state,advice,mode="model",budget=cap)
            row["budget_sweep_no_extra_api"][str(cap)]={"selection":sweep,"metrics":score(sweep,ep["gold"],advice)}
        row["binary_diagnostics_provisional"]=[]
        if item["method"]=="signals":
            # `needed` is direct answer evidence. PINNED constraints and call/result closure are policy obligations, not positive labels for this semantic question.
            truth_sets={"needed":set(ep["gold"].get("direct_evidence",ep["gold"]["exact"])),"constraint":pinned_ids(state),"exact":set(ep["gold"]["exact"])}
            for bid,values in advice.items():
                for dimension,truth in truth_sets.items():
                    p=values[dimension];y=int(bid in truth)
                    row["binary_diagnostics_provisional"].append({"id":bid,"dimension":dimension,"p_yes":p,"gold":y,"brier":(p-y)**2,"high_confidence_error":max(p,1-p)>=.9 and (p>=.5)!=bool(y)})
        recovered=recover(state,chosen,ep["later_query"],top_k=4,byte_budget=budget*2)
        # Retrieval only changes the selected packet. Its immutable archive remains full.
        later_gold={"needed":ep["gold"]["later_needed"],"exact":ep["gold"]["later_exact"],"stale":[]}
        archived_before=set(later_gold["needed"])-set(chosen["selected"])
        recovered_archived=archived_before & set(recovered["selected"])
        row["retrieval_probe"]={"retrieval":recovered,"metrics":score(recovered,later_gold),"later_query":ep["later_query"],
                                "archived_later_needed_before":sorted(archived_before),
                                "retrieval_exercised":bool(archived_before),
                                "archived_recovery_recall":len(recovered_archived)/len(archived_before) if archived_before else None,
                                "recovered_archived_ids":sorted(recovered_archived)}
        row["prefix_stability_proxy"]={"common_serialized_utf8_bytes":prefix_common_bytes(chosen["packet"],recovered["packet"]),"actual_cache_hits":None,"kv_memory":None}
    return row

def replay_item(item,client,steps=20,budget=3000,question_language="auto"):
    """Evolving candidates, independently evolved policies; gold cannot trigger recovery."""
    ep=item["episode"];timeline=[];later_at=steps-2
    for b in ep["state"]["blocks"]:timeline.append(deepcopy(b))
    for step in range(8,steps+1):
        timeline.append({"id":f"noise-{step}","text":f"Unrelated observation step {step}; not evidence that a requested operation succeeded.","source":"tool","kind":"note","step":step,"depends_on":[],"supersedes":[],"pair":"","scope":"experiment"})
    histories={};all_calls=[]
    for mode in ("keep_all","recency","lexical","model"):
        active=set();last=0;records=[];previous_query=ep["state"]["query"]
        for step in checkpoints(steps):
            archive=deepcopy(ep["state"]);archive["blocks"]=[b for b in timeline if b["step"]<=step];archive["step"]=step
            archive["query"]=ep["later_query"] if step>=later_at else ep["state"]["query"]
            observable_change=archive["query"]!=previous_query
            arrivals={b["id"] for b in archive["blocks"] if b["step"]>last}
            candidates=active|arrivals|pinned_ids(archive)
            if observable_change:
                # Query-driven retrieval, using the same lexical algorithm for every compressed arm.
                ranks=lexical_scores(archive)
                candidates.update(sorted(ranks,key=lambda x:(-ranks[x],x))[:4])
            if mode=="keep_all":candidates={b["id"] for b in archive["blocks"]}
            candidates=units(archive,candidates)
            current=deepcopy(archive);current["blocks"]=[b for b in archive["blocks"] if b["id"] in candidates]
            gold=ep["gold"] if step<later_at else {"needed":ep["gold"]["later_needed"],"exact":ep["gold"]["later_exact"],"stale":[]}
            # Early checkpoints may precede evidence. Evaluate only facts that actually exist by this step.
            existing={b["id"] for b in archive["blocks"]}
            gold={"needed":[i for i in gold["needed"] if i in existing],"exact":{i:v for i,v in gold["exact"].items() if i in existing},"stale":gold.get("stale",[])}
            advice=None;call=None
            if mode=="model":
                language="en" if question_language=="en" or (question_language=="auto" and ep["language"]=="en") else "zh"
                qs,mapping=questions(current,item["method"],language)
                call=client.request(current,qs);all_calls.append(call)
                if call["status"]!="ok":
                    records.append({"step":step,"status":call["status"],"call":call,"candidate_count":len(candidates),"metrics":None})
                    # Offline run exercises all plans without claiming model-derived trajectories.
                    if call["status"]=="dry_run":active=candidates;last=step;previous_query=archive["query"];continue
                    break
                advice=signals_from_answers(call["answers"],mapping)
            selection=select(current,advice,mode=mode,budget=budget,expected_revision=sha(current))
            active=set(selection["selected"])
            # Real archive never loses raw blocks even when candidates/active context do.
            entry={"step":step,"status":selection["status"],"query_changed":observable_change,
                   "candidate_count":len(candidates),"archive_count":len(existing),
                   "candidate_recall":len(candidates&set(gold["needed"]))/len(gold["needed"]) if gold["needed"] else None,
                   "selection":selection,"metrics":score(selection,gold,advice),"call":call,
                   "archive_sha256":sha(archive),"selected_from_current_not_oracle_future":True}
            records.append(entry);last=step;previous_query=archive["query"]
        histories[mode]=records
    return {"item_id":item["item_id"],"episode_id":ep["episode_id"],"group_id":ep["group_id"],"family":ep["family"],"language":ep["language"],"split":ep["split"],
            "method":item["method"],"status":"ok" if all(c['status']=='ok' for c in all_calls) else "dry_run" if all(c['status']=='dry_run' for c in all_calls) else "error",
            "steps":steps,"checkpoint_steps":checkpoints(steps),"histories":histories,"calls":all_calls,
            "fixture":ep,"evidence_only_not_llm_task_success":True}

def percentile(xs,p):
    if not xs:return None
    a=sorted(xs);k=(len(a)-1)*p;i=int(k)
    return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(k-i)

def group_bootstrap(pairs, seed=1729):
    """Cluster by template family, not translated records or individual blocks."""
    by=defaultdict(list)
    for family,diff in pairs:by[family].append(diff)
    if not by:return None
    vals=[statistics.mean(v) for v in by.values()];rng=random.Random(seed)
    samples=[statistics.mean(rng.choices(vals,k=len(vals))) for _ in range(1000)]
    return {"delta_family_weighted":statistics.mean(vals),"interval95_exploratory":[percentile(samples,.025),percentile(samples,.975)],"clusters":len(vals),
            "warning":"Few shared template families and provisional labels; not a production non-inferiority claim."}

def summarize(plan,rows):
    calls=[c for r in rows for c in r["calls"]];sent=[c for c in calls if c["request_sent"]]
    by={};deltas=[]
    if plan["suite"]=="retrieval":
        for language in ("zh","en","mixed"):
            items=[r for r in rows if r["language"]==language]
            good=[r for r in items if r.get("model_result") is not None]
            by[language]={"planned_records":len(items),"usable_records":len(good),
                          "lexical_top4_recall":statistics.mean(r["retrieval_baselines"]["lexical"]["topk_hit"] for r in items) if items else None,
                          "structured_top4_recall":statistics.mean(r["retrieval_baselines"]["structured"]["topk_hit"] for r in items) if items else None,
                          "jev_top1_recall":statistics.mean(r["model_result"]["top1_hit"] for r in good) if good else None,
                          "jev_top4_recall":statistics.mean(r["model_result"]["topk_hit"] for r in good) if good else None,
                          "mean_target_probability":statistics.mean(next(iter(r["model_result"]["target_probabilities"].values())) for r in good) if good else None}
    elif plan["suite"]!="replay":
        for language in ("zh","en","mixed"):
            for method in METHODS:
                items=[r for r in rows if r["language"]==language and r["method"]==method]
                good=[r for r in items if r["model_result"] is not None]
                metrics=[r["model_result"]["metrics"] for r in good]
                by[f"{language}/{method}"]={"planned_records":len(items),"usable_records":len(good),
                    "mean_evidence_recall":statistics.mean(m["evidence_recall"] for m in metrics) if metrics else None,
                    "mean_semantic_evidence_recall":statistics.mean(m["semantic_evidence_recall"] for m in metrics if m["semantic_evidence_recall"] is not None) if any(m["semantic_evidence_recall"] is not None for m in metrics) else None,
                    "mean_direct_evidence_recall":statistics.mean(m["direct_evidence_recall"] for m in metrics if m["direct_evidence_recall"] is not None) if any(m["direct_evidence_recall"] is not None for m in metrics) else None,
                    "records_missing_evidence":sum(not m["all_required_evidence_present"] for m in metrics),
                    "retrieval_exercised_records":sum(bool(r.get("retrieval_probe",{}).get("retrieval_exercised")) for r in good),
                    "mean_archived_recovery_recall":statistics.mean(r["retrieval_probe"]["archived_recovery_recall"] for r in good if r.get("retrieval_probe",{}).get("archived_recovery_recall") is not None) if any(r.get("retrieval_probe",{}).get("archived_recovery_recall") is not None for r in good) else None,
                    "raw_high_probability_false_demotions":sum(len(m["high_probability_false_demotion_ids"]) for m in metrics),
                    "budget_blocked":sum(r["model_result"]["selection"]["budget_overflow"] for r in good),
                    "mean_serialized_byte_reduction":statistics.mean(r["model_result"]["selection"]["byte_reduction"] for r in good) if good else None}
                for r in good:deltas.append((r["family"],r["model_result"]["metrics"]["semantic_evidence_recall"]-r["baselines"]["lexical"]["metrics"]["semantic_evidence_recall"]))
    else:
        for mode in ("keep_all","recency","lexical","model"):
            items=[(r,x) for r in rows for x in r["histories"][mode] if x.get("metrics") is not None]
            by[mode]={"scored_checkpoints":len(items),"missing_evidence_checkpoints":sum(not x["metrics"]["all_required_evidence_present"] for r,x in items),
                      "mean_evidence_recall":statistics.mean(x["metrics"]["evidence_recall"] for r,x in items) if items else None,
                      "budget_blocked":sum(x.get("status")=="blocked_budget" for r,x in items)}
    # Per-task diagnostic flips: identical repeat is a control, not an extra independent example.
    flips={};matched=defaultdict(dict)
    if plan["suite"]=="robustness":
        for r in rows:
            if r.get("model_result"):matched[r["episode_id"]][r["variant"]]=r
        for variant in ("repeat","reverse_options","reverse_blocks","injection","short_view"):
            n=changed=0
            for group in matched.values():
                if "base" not in group or variant not in group:continue
                left=group["base"]["model_result"]["advice"];right=group[variant]["model_result"]["advice"]
                for bid in left:
                    n+=1;changed+=left[bid].get("choice")!=right.get(bid,{}).get("choice")
            flips[variant]={"paired_block_observations":n,"flips":changed,"rate":changed/n if n else None,"independent_sample_count":None}
    binary=defaultdict(list)
    for r in rows:
        for d in r.get("binary_diagnostics_provisional",[]):binary[f"{r['language']}/{d['dimension']}"] .append(d)
    calibration={k:{"correlated_block_observations":len(v),"brier":statistics.mean(d["brier"] for d in v),"high_confidence_errors":sum(d["high_confidence_error"] for d in v),"production_threshold":None} for k,v in binary.items()}
    return {"binary_diagnostics_provisional":calibration,"schema":"context-summary-v0.2","suite":plan["suite"],"split":plan["split"],"plan_sha256":sha(plan),
            "execution":"live_api" if sent else "offline_no_model_results", "planned_condition_records":len(plan["items"]),"completed_records":len(rows),
            "statuses":dict(Counter(r["status"] for r in rows)),"model_requests":len(sent),"known_cost_subtotal_usd":sum(c["cost_usd"] or 0 for c in sent),
            "unmetered_requests":sum(c["cost_usd"] is None for c in sent),"input_tokens":sum((c["usage"] or {}).get("input_tokens",0) for c in sent),
            "p50_client_ms":percentile([c["wall_ms"] for c in sent if c["wall_ms"] is not None],.5),"p95_client_ms":percentile([c["wall_ms"] for c in sent if c["wall_ms"] is not None],.95),
            "by_language_method_or_policy":by,"paired_model_minus_lexical_recall":group_bootstrap(deltas),"perturbation_flips":flips,
            "caveats":["No real LLM downstream task completion measured. Evidence retention is a proxy.","Byte reduction is not provider token or cost reduction.",
                       "Protected instructions are pinned by code; successful pinning is not a model capability score.","Threshold .9 is exploratory, not calibrated or production approved.",
                       "Fixtures are provisional and share template families. Test split must not be used for prompt tuning.","No unsupported causal claim from a single timed comparison; fan-out totals include HTTP overhead.","Unknown costs are not zero."]}

def markdown(summary):
    out=["# Context Curator 实验报告", "",f"执行：`{summary['execution']}`；suite=`{summary['suite']}`；split=`{summary['split']}`。", "",
         "**这是合成场景的证据保留测试，不是完整 coding 任务成功率。**", "",
         f"真实模型请求：{summary['model_requests']}；已知模型费用小计：${summary['known_cost_subtotal_usd']:.6f}；未计量请求：{summary['unmetered_requests']}。", "",
         "|组|可评分记录/检查点|必要证据平均召回|遗漏证据记录数|", "|---|---:|---:|---:|"]
    if summary["suite"]=="retrieval":
        out=["# Context Curator 检索实验报告","",f"执行：`{summary['execution']}`；split=`{summary['split']}`。","",
             "**此实验把后续目标视为归档，隔离测试检索，不测压缩策略。**","",
             f"真实模型请求：{summary['model_requests']}；已知模型费用小计：${summary['known_cost_subtotal_usd']:.6f}；未计量请求：{summary['unmetered_requests']}。","",
             "|语言|记录|lexical top4|structured top4|Jev top1|Jev top4|","|---|---:|---:|---:|---:|---:|"]
        for k,v in summary["by_language_method_or_policy"].items():
            fmt=lambda x: "unknown" if x is None else f"{x:.3f}"
            out.append(f"|{k}|{v['usable_records']}|{fmt(v['lexical_top4_recall'])}|{fmt(v['structured_top4_recall'])}|{fmt(v['jev_top1_recall'])}|{fmt(v['jev_top4_recall'])}|")
    else:
        for k,v in summary["by_language_method_or_policy"].items():
            recall=v.get("mean_evidence_recall")
            out.append(f"|{k}|{v.get('usable_records',v.get('scored_checkpoints',0))}|{'unknown' if recall is None else f'{recall:.3f}'}|{v.get('records_missing_evidence',v.get('missing_evidence_checkpoints',0))}|")
    out += ["", "## 解释边界", "", *["- "+x for x in summary["caveats"]], "", "逐条失败、有效输入、候选召回、引用依赖、序列回放和费用见 results.jsonl / summary.json；不把 API 返回成功解释为任务成功。", ""]
    return "\n".join(out)

def execute(plan,out,cfg=None,live=False,budget=3000,question_language="auto",send=None):
    out=Path(out)
    if out.exists():raise ExperimentError("output_exists")
    if question_language not in {"auto","zh","en"}:raise ExperimentError("invalid_question_language")
    config=validate_config(dict(DEFAULT if cfg is None else cfg))
    if isinstance(budget,bool) or not isinstance(budget,int) or not 1<=budget<=100000:
        raise ExperimentError("invalid_packet_budget")
    if config["backend"]!=plan["backend"]:raise ExperimentError("plan_backend_mismatch")
    if plan["max_model_requests"]>config["max_requests"]:raise ExperimentError("plan_exceeds_request_cap")
    out.mkdir(parents=True)
    (out/"plan.json").write_text(dumps(plan),encoding="utf-8")
    (out/"config.json").write_text(dumps(config),encoding="utf-8")
    import platform,os
    manifest={"commit":os.environ.get("GITHUB_SHA"),"runtime":{"python":platform.python_version(),"platform":platform.platform()},
              "plan_sha256":sha(plan),"config_sha256":sha(config),"live_authorized":live,"budget_bytes":budget,"question_language":question_language,
              "code_hashes":{p.name:sha(p.read_text(encoding="utf-8")) for p in Path(__file__).parent.glob("*.py")}}
    (out/"manifest.json").write_text(dumps(manifest),encoding="utf-8")
    kwargs={"cfg":config,"live":live,"ledger_path":out/"ledger.json"}
    if send is not None:kwargs["send"]=send
    client=Client(**kwargs);rows=[]
    with (out/"results.jsonl").open("x",encoding="utf-8") as f:
        for item in plan["items"]:
            row=replay_item(item,client,plan["steps"],budget,question_language) if plan["suite"]=="replay" else retrieval_lab.run_item(item,client,question_language) if plan["suite"]=="retrieval" else call_item(item,client,budget,question_language)
            rows.append(row);f.write(dumps(row)+"\n");f.flush()
            if live and client.stop:break
    result=summarize(plan,rows)
    result["backend_stop_reason"]=client.stop
    (out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (out/"report.md").write_text(markdown(result),encoding="utf-8")
    failures=[r for r in rows if r["status"] in {"error","blocked"} or (r.get("model_result") and (not r["model_result"]["metrics"]["all_required_evidence_present"] or r["model_result"]["selection"]["budget_overflow"]))]
    if plan["suite"]=="retrieval":
        failures=[r for r in rows if r["status"] in {"error","blocked"} or (r.get("model_result") and not r["model_result"]["topk_hit"])]
    elif plan["suite"]=="replay":
        failures=[r for r in rows if r["status"] in {"error","blocked"} or any(
            x.get("metrics") is not None and (not x["metrics"]["all_required_evidence_present"] or x.get("status")=="blocked_budget")
            for x in r["histories"]["model"])]
    (out/"failures.jsonl").write_text("".join(dumps(r)+"\n" for r in failures),encoding="utf-8")
    scan(out,client.key)
    return result

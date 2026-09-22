"""Simplest-sufficient retrieval gate.

Runs the cheaper 64-block + short-question + deterministic closure path across
all stable retrieval128/dev fixtures before considering the more expensive
relation-aware two-pass router. No downstream LLM calls.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import statistics
from curator.core import ExperimentError, dumps
from .fixtures import cases, FIXTURE_VERSION
from .gateway import Gateway, scan
from . import runner as r

STAGE="short-no-anchor-retrieval128-dev"
EXPECTED_CASES=18
EXPECTED_JEV_REQUESTS=54


def retrieve(case,gateway):
    state=case["state"]; cid=case["case_id"]
    calls=[]; survivors=[]; stages=[]
    shards=r.shard_states(state)
    for i,shard in enumerate(shards):
        qs,mapping=r.relevance_questions(shard)
        call=gateway.request("jev",shard,qs,f"{cid}/short/shard-{i}")
        calls.append(call)
        ranked=r.ranking(call,mapping)
        chosen=ranked[:r.LOCAL_K]
        survivors.extend(chosen)
        stages.append({"shard":i,"selected_ids":chosen,"ranking":ranked})
    union=r.subset(state,survivors)
    qs,mapping=r.relevance_questions(union)
    call=gateway.request("jev",union,qs,f"{cid}/short/merge")
    calls.append(call)
    merged=r.ranking(call,mapping)
    selected=r.pack(state,merged)
    live=all(c["status"]=="ok" for c in calls)
    required=set(case["gold"]["required_ids"])
    metrics=None if not live else {
      "local_recall":len(required & set(survivors))/len(required),
      "final_recall":len(required & set(selected["ids"]))/len(required),
      "all_required_present":required.issubset(selected["ids"]),
      "packet_bytes":selected["byte_count"],
      "budget_skipped_ids":selected["budget_skipped_ids"]}
    return {"case_id":cid,"family":case["family"],"language":case["language"],
            "group_id":case["group_id"],"state_hash":case["state_hash"],
            "calls":calls,"local_stages":stages,"survivors":survivors,
            "merge_ranking":merged,"selected":selected,"metrics":metrics}


def run(out:Path,live=False):
    if out.exists(): raise ExperimentError("output_exists")
    out.mkdir(parents=True)
    pool=cases("dev",128)
    if len(pool)!=EXPECTED_CASES: raise ExperimentError("short_gate_case_count_drift")
    planned=sum(len(r.shard_states(c["state"]))+1 for c in pool)
    if planned!=EXPECTED_JEV_REQUESTS: raise ExperimentError("short_gate_request_count_drift")
    gateway=Gateway(out,live_jev=live)
    rows=[]
    try:
        for case in pool:
            row=retrieve(case,gateway); rows.append(row)
            with (out/"retrieval.jsonl").open("a",encoding="utf-8") as f:
                f.write(dumps(row)+"\n")
            if gateway.stop: break
    except ExperimentError as e:
        gateway.stop=gateway.stop or str(e)
    scored=[x for x in rows if x["metrics"] is not None]
    by_lang={}
    for lang in ("zh","en","mixed"):
        g=[x for x in scored if x["language"]==lang]
        by_lang[lang]={"cases":len(g),
          "complete":sum(x["metrics"]["all_required_present"] for x in g),
          "mean_final_recall":statistics.mean(x["metrics"]["final_recall"] for x in g) if g else None}
    by_family={}
    for fam in sorted({x["family"] for x in rows}):
        g=[x for x in scored if x["family"]==fam]
        by_family[fam]={"cases":len(g),"complete":sum(x["metrics"]["all_required_present"] for x in g)}
    sent=[x for x in gateway.receipts if x.get("request_sent") and not x.get("reused")]
    summary={"stage":STAGE,"fixture_version":FIXTURE_VERSION,
      "execution":"live" if live else "offline_no_model_results",
      "expected_cases":EXPECTED_CASES,"completed_cases":len(rows),
      "planned_jev_requests":EXPECTED_JEV_REQUESTS,"newly_sent_requests":len(sent),
      "complete_cases":None if not scored else sum(x["metrics"]["all_required_present"] for x in scored),
      "mean_local_recall":None if not scored else statistics.mean(x["metrics"]["local_recall"] for x in scored),
      "mean_final_recall":None if not scored else statistics.mean(x["metrics"]["final_recall"] for x in scored),
      "mean_packet_bytes":None if not scored else statistics.mean(x["metrics"]["packet_bytes"] for x in scored),
      "by_language":by_lang,"by_family":by_family,
      "jev_input_tokens":sum((x.get("usage") or {}).get("input_tokens",0) for x in sent) if sent else None,
      "known_cost_usd":sum(x.get("cost_usd") or 0 for x in sent),
      "wall_ms_sum":sum(x.get("wall_ms") or 0 for x in sent),
      "stop_reason":gateway.stop,
      "gate_passed":bool(scored) and len(scored)==EXPECTED_CASES and all(x["metrics"]["all_required_present"] for x in scored)}
    (out/"summary.json").write_text(dumps(summary),encoding="utf-8")
    lines=["# Short-no-anchor retrieval128/dev gate","",
      f"execution: `{summary['execution']}`; fixture: `{FIXTURE_VERSION}`; stop: `{gateway.stop}`.","",
      "|metric|result|","|---|---:|",
      f"|cases|{len(scored)}/{EXPECTED_CASES}|" if scored else f"|cases|unknown/{EXPECTED_CASES}|",
      f"|all required complete|{summary['complete_cases']}/{EXPECTED_CASES}|" if scored else "|all required complete|unknown|",
      f"|mean local recall|{summary['mean_local_recall']}|",
      f"|mean final recall|{summary['mean_final_recall']}|",
      f"|mean packet bytes|{summary['mean_packet_bytes']}|",
      f"|new Jev requests|{summary['newly_sent_requests']}/{EXPECTED_JEV_REQUESTS}|",
      f"|Jev input tokens|{summary['jev_input_tokens']}|",
      f"|known list-cost USD|{summary['known_cost_usd']:.6f}|",
      f"|gate passed|{summary['gate_passed']}|","",
      "|language|complete/cases|mean final recall|","|---|---:|---:|"]
    for lang,v in by_lang.items():
        lines.append(f"|{lang}|{v['complete']}/{v['cases']}|{v['mean_final_recall']}|")
    lines += ["","If this gate is 18/18, prefer the simpler retrieval path for the next economic/coding smoke.",
      "If any final evidence is missing, run the relation-aware v0.6 path on the same frozen fixtures.",
      "This is an authored synthetic retrieval gate, not a production error-rate estimate."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    gateway.persist(); scan(out,tuple(gateway.keys.values()))
    return summary


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--allow-jev-paid",action="store_true")
    a=p.parse_args(argv)
    try:
        s=run(a.out,a.allow_jev_paid)
        print(f"Report: {a.out/'report.md'}; sent={s['newly_sent_requests']}; pass={s['gate_passed']}; stop={s['stop_reason']}")
        return 0 if not s["stop_reason"] else 2
    except ExperimentError as e:
        print(str(e)); return 2

if __name__=="__main__":
    raise SystemExit(main())

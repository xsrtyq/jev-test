"""Fixed-trajectory cache/window economics smoke benchmark."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from curator.core import ExperimentError, dumps, lexemes
from .fixtures import cache_trace
from .gateway import Gateway, scan

STRATEGIES=("append_all","rewrite_each","window_rules","window_jev")
TOP_K=6
# Simulate a realistic stable agent prefix (system/tool schemas) large enough
# for provider prompt-cache mechanisms to have a chance to engage. The arm
# identifier remains before this block so cache warming cannot leak across arms.
STABLE_PROTOCOL = "\n".join(
    f"synthetic_tool_{i:03d}: read-only descriptor {i:03d}; no side effects; ignore unless explicitly referenced."
    for i in range(256)
)

def rank_rules(records,query):
    q=lexemes(query)
    return sorted(records,key=lambda x:(-len(q & lexemes(x["text"])),x["id"]))

def jev_select(gateway,records,goal,slot):
    if not records: return []
    state={"goal":goal,"query":"Select historical evidence likely needed during the next work window.",
           "step":1,"scope":"synthetic","blocks":[{"id":r["id"],"text":r["text"],"source":"history","kind":"note","step":i,
           "depends_on":[],"supersedes":[],"pair":"","scope":"synthetic"} for i,r in enumerate(records)],
           "background":"Synthetic fixed trajectory. Selection is advisory only."}
    qs={f"r{i}":{"type":"noul","instructions":f"blocks[{i}] id={b['id']}: likely needed to continue this window goal?",
        "criteria":{"true":"Useful for the next window.","false":"Not needed."}} for i,b in enumerate(state["blocks"])}
    call=gateway.jev(state,qs,slot)
    if call["status"]=="dry_run": return records[:TOP_K]
    if call["status"]!="ok": raise ExperimentError("jev_window_selection_failed")
    scored=[(call["answers"][f"r{i}"]["noul"],r) for i,r in enumerate(records)]
    return [r for _,r in sorted(scored,key=lambda x:(-x[0],x[1]["id"]))[:TOP_K]]

def system(strategy):
    return {"role":"system","content":(
      f"CACHE_BENCH_STRATEGY={strategy}. This is a synthetic continuation replay. "
      "The stable synthetic tool catalog below is inert cacheable protocol text; do not use it as evidence. "
      "Answer exactly one JSON object {\"answer\": <allowed value>}. Use supplied history; do not invent facts.\n"
      + STABLE_PROTOCOL)}

def evidence_message(records,goal):
    return {"role":"user","content":"WINDOW GOAL: "+goal+"\nHISTORICAL EVIDENCE:\n" +
            "\n".join(f"[{r['id']}] {r['text']}" for r in records)}

def question_message(turn):
    return {"role":"user","content":"QUESTION: "+turn["q"]+"\nALLOWED: "+", ".join(turn["choices"])}

def common_prefix_bytes(a,b):
    aa=dumps(a).encode(); bb=dumps(b).encode(); n=min(len(aa),len(bb)); i=0
    while i<n and aa[i]==bb[i]: i+=1
    return i

def run(out:Path,*,live_jev=False,live_llm=False):
    if out.exists(): raise ExperimentError("output_exists")
    out.mkdir(parents=True); g=Gateway(out,live_jev=live_jev,live_llm=live_llm)
    trace=cache_trace(); rows=[]; archive=[]
    for strategy in STRATEGIES:
        archive=[]; messages=[system(strategy)]; previous_body=None; prior_answers=[]
        selected_for_window=[]
        for wi,window in enumerate(trace["windows"]):
            if wi>0:
                if strategy=="window_rules": selected_for_window=rank_rules(archive,window["goal"])[:TOP_K]
                elif strategy=="window_jev": selected_for_window=jev_select(g,archive,window["goal"],f"{strategy}/window-{wi}/select")
                if strategy in ("window_rules","window_jev"):
                    messages=[system(strategy),evidence_message(selected_for_window,window["goal"])]
            current=[]
            for ti,(event,turn) in enumerate(zip(window["events"],window["turns"])):
                current.append(event)
                if strategy=="append_all":
                    messages.append({"role":"user","content":f"EVENT [{event['id']}]: {event['text']}"})
                    call_messages=messages+[question_message(turn)]
                elif strategy=="rewrite_each":
                    visible=rank_rules(archive+current,turn["q"])[:TOP_K]
                    call_messages=[system(strategy),evidence_message(visible,window["goal"]),question_message(turn)]
                else:
                    messages.append({"role":"user","content":f"EVENT [{event['id']}]: {event['text']}"})
                    call_messages=messages+[question_message(turn)]
                body={"model":"deepseek-v4-flash","messages":call_messages,"response_format":{"type":"json_object"},"max_tokens":512}
                prefix=common_prefix_bytes(previous_body,body) if previous_body is not None else 0
                call=g.llm(call_messages,turn["choices"],f"{strategy}/w{wi}/t{ti}")
                correct=None if call["status"]=="dry_run" else call.get("answer")==turn["gold"]
                usage=call.get("usage") or {}
                rows.append({"strategy":strategy,"window":wi,"turn":ti,"gold":turn["gold"],"correct":correct,
                             "call":call,"prefix_bytes":prefix,"body_bytes":len(dumps(body).encode())})
                previous_body=body
                # Fixed replay: subsequent prefixes use canonical gold, not provider output.
                if strategy!="rewrite_each":
                    messages += [question_message(turn),{"role":"assistant","content":dumps({"answer":turn["gold"]})}]
            archive.extend(window["events"])
    summary={"trace_id":trace["trace_id"],"execution":"live" if (live_jev or live_llm) else "offline_no_model_results",
             "gateway":g.summary(),"strategies":{}}
    for strategy in STRATEGIES:
        rr=[x for x in rows if x["strategy"]==strategy]; calls=[x["call"] for x in rr]
        cached=[(c.get("usage") or {}).get("cached_input_tokens") for c in calls]
        inp=[(c.get("usage") or {}).get("input_tokens") for c in calls]
        llm_cost=sum(c.get("cost_usd") or 0 for c in calls)
        summary["strategies"][strategy]={
          "calls":len(rr),"correct":None if not live_llm else sum(x["correct"] is True for x in rr),
          "input_tokens":None if any(x is None for x in inp) else sum(inp),
          "cached_input_tokens":None if any(x is None for x in cached) else sum(cached),
          "uncached_input_tokens":None if any(x is None for x in inp+cached) else sum(i-c for i,c in zip(inp,cached)),
          "known_llm_cost_usd":llm_cost,
          "production_trace_cost_usd":llm_cost + (g.costs["jev"] if strategy=="window_jev" else 0.0),
          "mean_prefix_reuse_ratio":sum(x["prefix_bytes"]/max(1,x["body_bytes"]) for x in rr)/len(rr)}
    (out/"rows.jsonl").write_text("\n".join(dumps(x) for x in rows)+"\n",encoding="utf-8")
    (out/"summary.json").write_text(dumps(summary),encoding="utf-8")
    lines=["# Window/cache economics smoke","",
      "|strategy|correct/12|input tokens|cached tokens|uncached tokens|LLM cost USD|trace cost incl. Jev|mean byte-prefix reuse|",
      "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k,v in summary["strategies"].items():
        lines.append(f"|{k}|{v['correct'] if v['correct'] is not None else 'unknown'}/12|{v['input_tokens']}|{v['cached_input_tokens']}|{v['uncached_input_tokens']}|{v['known_llm_cost_usd']:.6f}|{v['production_trace_cost_usd']:.6f}|{v['mean_prefix_reuse_ratio']:.3f}|")
    lines += ["",f"Jev selector cost (experiment actual): ${g.costs['jev']:.6f}.",
      "This measures the connected relay's reported cache fields and structural prefix reuse. It is not a Codex/OpenAI KV-cache measurement."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    scan(out,tuple(g.keys.values())); return summary

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--out",type=Path,required=True)
    p.add_argument("--allow-jev-paid",action="store_true"); p.add_argument("--allow-llm-paid",action="store_true")
    a=p.parse_args(argv)
    if a.allow_llm_paid and not a.allow_jev_paid:
        print("cache_probe_live_requires_both_authorizations"); return 2
    try:
        s=run(a.out,live_jev=a.allow_jev_paid,live_llm=a.allow_llm_paid)
        print(f"Report: {a.out/'report.md'}; stop={s['gateway']['stop']}")
        return 0 if not s["gateway"]["stop"] else 2
    except ExperimentError as e: print(str(e)); return 2
if __name__=="__main__": raise SystemExit(main())

"""CLI for an isolated evidence benchmark. Live spending always requires --allow-paid."""
import argparse
import json
import os
from pathlib import Path
from .client import DEFAULT, scan
from .core import ExperimentError, loads, dumps, sha, cache_scenario
from .runner import make_plan,execute,SUITES

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="cmd",required=True)
    for cmd in ("plan","run"):
        s=sub.add_parser(cmd);s.add_argument("--suite",choices=SUITES,default="quick");s.add_argument("--split",choices=("dev","calibration","test"),default="dev")
        s.add_argument("--steps",type=int,choices=(10,20,50),default=20);s.add_argument("--out",type=Path,required=True)
        s.add_argument("--seed",type=int,default=1729);s.add_argument("--backend",choices=("jev","llm"),default="jev")
        if cmd=="run":
            s.add_argument("--allow-paid",action="store_true");s.add_argument("--config",type=Path);s.add_argument("--budget-bytes",type=int,default=3000)
            s.add_argument("--question-language",choices=("auto","zh","en"),default="auto")
            s.add_argument("--frozen-plan",type=Path,help="Use exact plan, ignoring plan-generation flags; hash is retained")
    s=sub.add_parser("scan");s.add_argument("root",type=Path)
    s=sub.add_parser("cache");s.add_argument("--out",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        if args.cmd=="scan":
            scan(args.root,os.environ.get("TYPESAFE_API_KEY","") or os.environ.get("OPENAI_API_KEY",""));print("Artifact scan passed");return 0
        if args.out.exists():raise ExperimentError("output_exists")
        if args.cmd=="cache":
            result=cache_scenario(100000,30000,.976,1.,.1,.01,5)
            args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2),encoding="utf-8");print("Assumptions only; no API or cache measured");return 0
        plan=make_plan(args.suite,args.split,args.seed,args.steps,args.backend)
        if args.cmd=="plan":
            args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(dumps(plan),encoding="utf-8")
            print(f"Frozen plan: {plan['max_model_requests']} maximum requests; {plan['scenario_groups']} groups/{plan['template_families']} families; hash={sha(plan)}");return 0
        if args.frozen_plan:plan=loads(args.frozen_plan.read_text(encoding="utf-8"))
        if plan["backend"]=="llm" and not args.config:raise ExperimentError("verified_llm_config_required")
        cfg=loads(args.config.read_text(encoding="utf-8")) if args.config else DEFAULT
        result=execute(plan,args.out,cfg,args.allow_paid,args.budget_bytes,args.question_language)
        print(f"Report: {args.out/'report.md'}; real_model_requests={result['model_requests']}; execution={result['execution']}")
        if result["completed_records"]<result["planned_condition_records"] or result["statuses"].get("error",0) or result["unmetered_requests"] or result.get("backend_stop_reason"):return 2
        return 0
    except ExperimentError as e:print(str(e));return 2
    except Exception:print("experiment_failed_details_not_logged");return 2

if __name__=="__main__":raise SystemExit(main())

"""CLI for Jev -> LLM decision assistance experiments."""
import argparse
import json
from pathlib import Path
from curator.client import DEFAULT
from curator.core import ExperimentError,loads,dumps,sha
from .runner import make_plan as make_classic_plan,execute as execute_classic,SUITES as CLASSIC_SUITES
from .hard_runner import make_plan as make_hard_plan,execute as execute_hard
SUITES=CLASSIC_SUITES+("hard",)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("plan")
    s.add_argument("--suite",choices=SUITES,default="quick")
    s.add_argument("--split",choices=("dev","calibration","test"),default="dev")
    s.add_argument("--seed",type=int,default=1729)
    s.add_argument("--out",type=Path,required=True)
    s=sub.add_parser("run")
    s.add_argument("--plan",type=Path,required=True)
    s.add_argument("--llm-config",type=Path,required=True)
    s.add_argument("--out",type=Path,required=True)
    s.add_argument("--allow-jev-paid",action="store_true")
    s.add_argument("--allow-llm-paid",action="store_true")
    s.add_argument("--question-language",choices=("auto","zh","en"),default="auto")
    args=p.parse_args(argv)
    try:
        if args.cmd=="plan":
            if args.out.exists(): raise ExperimentError("output_exists")
            plan=make_hard_plan(args.split,args.seed) if args.suite=="hard" else make_classic_plan(args.suite,args.split,args.seed)
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(dumps(plan),encoding="utf-8")
            print(f"Decision-assist plan: {plan['case_records']} records; max Jev={plan['jev_requests_max']}; max LLM={plan['llm_requests_max']}; hash={sha(plan)}")
            return 0
        plan=loads(args.plan.read_text(encoding="utf-8"))
        llm_cfg=loads(args.llm_config.read_text(encoding="utf-8"))
        summary=execute_hard(plan,args.out,DEFAULT,llm_cfg,args.allow_jev_paid,args.allow_llm_paid,args.question_language) if plan.get("suite")=="hard" else execute_classic(plan,args.out,DEFAULT,llm_cfg,args.allow_jev_paid,args.allow_llm_paid,args.question_language)
        print(f"Report: {args.out/'report.md'}; execution={summary['execution']}")
        if summary["completed_records"]<summary["planned_records"]: return 2
        if summary["statuses"].get("error",0) or summary["statuses"].get("partial",0): return 2
        if summary["jev_backend"].get("stop_reason") or summary["llm_backend"].get("stop_reason"): return 2
        return 0
    except ExperimentError as e:
        print(str(e));return 2
    except Exception:
        print("decision_assist_failed_details_not_logged");return 2

if __name__=="__main__":
    raise SystemExit(main())

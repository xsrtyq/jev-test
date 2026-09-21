"""Manual, bounded evidence-first experiments. Defaults to zero network calls."""
import argparse
import os
from pathlib import Path
from curator.core import ExperimentError, dumps, loads, sha
from .runner import make_plan, execute, STAGES
from .gateway import scan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--stage", choices=STAGES, default="smoke")
    p.add_argument("--split", choices=("dev", "calibration", "test"), default="dev")
    p.add_argument("--seed", type=int, default=601)
    p.add_argument("--case-id", default=None)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--resume", type=Path)
    p.add_argument("--allow-jev-paid", action="store_true")
    p.add_argument("--allow-llm-paid", action="store_true")
    p = sub.add_parser("scan")
    p.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            if args.out.exists():
                raise ExperimentError("output_exists")
            plan = make_plan(args.stage, args.split, args.seed, args.case_id)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(dumps(plan), encoding="utf-8")
            print(f"Frozen plan {sha(plan)}: {len(plan['items'])} cases, maximum calls {plan['request_caps']}")
            return 0
        if args.command == "scan":
            scan(args.root, (os.environ.get("TYPESAFE_API_KEY", ""), os.environ.get("A2AGENT_API_KEY", "")))
            print("Artifact scan passed")
            return 0
        plan = loads(args.plan.read_text(encoding="utf-8"))
        result = execute(plan, args.out, live_jev=args.allow_jev_paid, live_llm=args.allow_llm_paid, resume=args.resume)
        print(f"Report: {args.out / 'report.md'}; execution={result['execution']}; stop={result['stop_reason']}")
        if result["stop_reason"] or result["prepared_cases"] != result["expected_cases"] or result["recorded_downstream_trials"] != result["expected_downstream_trials"]:
            return 2
        # A completed experiment may contain wrong labels or censored outputs.
        # Green means the planned observations were recorded, not quality passed.
        return 0
    except ExperimentError as e:
        print(str(e)); return 2
    except Exception as e:
        print("experiment_failed_" + type(e).__name__); return 2


if __name__ == "__main__":
    raise SystemExit(main())

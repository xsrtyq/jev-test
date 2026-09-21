"""Bounded smoke run for GitHub Actions. Dry by default; never accepts keys as CLI args."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import os
from pathlib import Path
import sys

import jev_lab as lab
from fixtures import make_cases

COUNTS = (9, 30, 90)
FAMILIES = ("routing", "error", "relevance")


def select_cases(count=30, variant="base", question_language=None):
    """Round-robin task families, retaining complete zh/en/mixed triples."""
    if count not in COUNTS:
        raise lab.LabError("unsupported_case_count")
    cases = make_cases(variant, question_language)
    lab.validate_cases(cases)
    groups = defaultdict(dict)
    for case in cases:
        groups[case["family"]].setdefault(case["group_id"], []).append(case)
    pools = {family: list(groups[family].values()) for family in FAMILIES}
    selected = []
    for index in range(count // 3):
        family = FAMILIES[index % len(FAMILIES)]
        selected.extend(pools[family][index // len(FAMILIES)])
    lab.validate_cases(selected)
    if len(selected) != count:
        raise lab.LabError("fixture_group_size_changed")
    return selected


def bounded_config(base, count):
    cfg = dict(base)
    if cfg.get("kind") != "jev":
        raise lab.LabError("cloud_smoke_requires_official_jev")
    cfg.update(max_calls=count, budget_usd=0.25, reserve_usd=0.005,
               max_payload_bytes=32000, timeout_s=15)
    lab.validate_config(cfg)
    return cfg


def scan_artifacts(root, secret=""):
    """Safety check, not a claim that arbitrary transformed secrets can be detected."""
    needle = secret.encode("utf-8") if secret else None
    for path in root.rglob("*"):
        if path.is_symlink():
            raise lab.LabError("artifact_symlink_blocked")
        if path.is_file():
            if path.stat().st_size > 10_000_000:
                raise lab.LabError("unexpected_artifact_size")
            content = path.read_bytes()
            if (needle and needle in content) or b"apikey_" in content:
                raise lab.LabError("credential_pattern_in_artifact_upload_blocked")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case-count", type=int, choices=COUNTS, default=30)
    parser.add_argument("--variant", choices=("base", "reverse_options", "injection", "distractor"), default="base")
    parser.add_argument("--question-language", choices=("auto", "zh", "en"), default="auto")
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--scan-only", action="store_true")
    args = parser.parse_args(argv)
    secret = os.environ.get("TYPESAFE_API_KEY", "")
    try:
        if args.scan_only:
            if not args.out.is_dir():
                raise lab.LabError("no_artifact_directory")
            scan_artifacts(args.out, secret)
            print("Artifact scan passed; no credentials printed.")
            return 0
        if args.out.exists():
            raise lab.LabError("output_exists_choose_a_new_path")
        if args.allow_paid and not secret:
            raise lab.LabError("missing_TYPESAFE_API_KEY_repository_secret")
        cases = select_cases(args.case_count, args.variant,
                             None if args.question_language == "auto" else args.question_language)
        source = Path(__file__).resolve().parent / "config" / "jev.json"
        cfg = bounded_config(lab.decode(source.read_text(encoding="utf-8")), args.case_count)
        args.out.mkdir(parents=True)
        data = args.out / "cases.jsonl"
        data.write_text("".join(lab.encode(c) + "\n" for c in cases), encoding="utf-8")
        config = args.out / "config.json"
        lab.write_json(config, cfg)
        lab.write_json(args.out / "plan.json", {
            "kind": "authored_provisional_smoke_not_production_benchmark",
            "records": len(cases), "independent_groups": len({c["group_id"] for c in cases}),
            "language_counts": dict(Counter(c["language"] for c in cases)),
            "family_counts": dict(Counter(c["family"] for c in cases)),
            "variant": args.variant, "question_language": args.question_language,
            "live_requested": args.allow_paid, "source_commit": os.environ.get("GITHUB_SHA"),
            "model": cfg["model"], "max_requests": args.case_count,
            "budget_estimate_usd": cfg["budget_usd"], "price_snapshot": cfg["price_verified_at"],
            "warnings": ["No local model or small-LLM comparison.",
                         "This measures static relevance, not a long-running context manager.",
                         "Budget resets for each manual run and is not an invoice guarantee.",
                         "Hosted CI execution may have a separate GitHub charge."]})
        run_args = ["run", "--data", str(data), "--config", str(config),
                    "--out", str(args.out / "jev"), "--limit", str(args.case_count)]
        if args.allow_paid:
            run_args += ["--allow-network", "--allow-paid"]
        code = lab.main(run_args)
        scan_artifacts(args.out, secret)
        return code
    except lab.LabError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("cloud_smoke_failed_details_not_logged", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Recompute the five frozen archive artifacts, with source hashes; no API use."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import zipfile


def read_zip(path):
    with zipfile.ZipFile(path) as z:
        if sum(x.file_size for x in z.infolist()) > 50_000_000:
            raise ValueError("oversized_artifact")
        rows = [json.loads(x) for x in z.read("results.jsonl").decode().splitlines() if x]
        plan = json.loads(z.read("plan.json"))
    return rows, plan


def audit(root):
    root = Path(root)
    filenames = ["context-hard-v04.zip", "context-hard-calibration.zip", "context-hard-test.zip",
                 "assist-hard-complete.zip", "assist-hard-resume-proxy-zh.zip"]
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in filenames}
    context = {}
    for name, split in zip(filenames[:3], ("dev", "calibration", "test")):
        rows, plan = read_zip(root / name)
        assert plan["dataset_version"] == "retrieval-hard-0.4.0-authored"
        assert plan["split"] == split and len(rows) == 12 and all(r["status"] == "ok" for r in rows)
        context[split] = {"records": len(rows), "full64_top1": sum(r["model_result"]["full"]["top1_hit"] for r in rows),
                          "prefilter_top16": sum(r["deterministic"]["candidate_recall"] for r in rows)}
    original, plan = read_zip(root / filenames[3]); resumed, subplan = read_zip(root / filenames[4])
    original_cases = {x["case"]["case_id"]: x for x in plan["items"]}
    assert len(resumed) == 1
    case_id = resumed[0]["case_id"]
    assert original_cases[case_id] == subplan["items"][0]
    blocked = next(x for x in original if x["case_id"] == case_id)
    assert not blocked["trials"]
    assert not blocked["jev"]["direct_call"]["request_sent"]
    merged = [r for r in original if r["case_id"] != case_id] + resumed
    assert len(merged) == 12 and len({r["case_id"] for r in merged}) == 12
    result = {}
    for arm in ("raw", "neutral", "jev_direct", "jev_signals", "wrong_direct"):
        trials = [t for row in merged for t in row["trials"]]
        calls = [t["calls"][arm] for t in trials]
        assert len(calls) == 24 and all(c["request_sent"] for c in calls)
        result[arm] = {"attempts": 24, "correct_and_completed": sum(t["scores"].get(arm) == 1 for t in trials),
                       "output_caps": sum(c.get("error") == "llm_output_limit" for c in calls),
                       "input_tokens": sum(c["usage"]["input_tokens"] for c in calls),
                       "output_tokens": sum(c["usage"]["output_tokens"] for c in calls),
                       "reasoning_tokens": sum(c["usage"].get("reasoning_tokens", 0) for c in calls)}
    return {"source_sha256": hashes, "context": context, "assist": result,
            "status": "recomputed_from_existing_artifacts_no_new_calls",
            "limitations": ["The old wrong_direct prompt explicitly disclosed synthetic_known_wrong to the model; not a blinded robustness test.",
                            "Old retrieval distractors and single-target templates do not establish production-scale retrieval quality.",
                            "No result establishes universal inferiority of sparse retrieval or superiority over a multilingual embedding baseline."]}


def main():
    p = argparse.ArgumentParser(); p.add_argument("root", type=Path); p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists(): raise ValueError("output_exists")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(audit(args.root), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": main()

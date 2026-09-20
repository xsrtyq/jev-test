#!/usr/bin/env python3
"""Isolated, stdlib-only decision lab. No model output can execute an action."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "0.1.0"
MAX_RESPONSE_BYTES = 2_000_000
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class LabError(Exception):
    """Only controlled, non-secret diagnostic codes should be logged."""


def encode(value: Any) -> str:
    # Preserve insertion order: option order is an experimental variable.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LabError("duplicate_json_key")
        result[key] = value
    return result


def decode(text: str):
    try:
        return json.loads(text, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(LabError("nonfinite_json")))
    except (ValueError, TypeError) as exc:
        raise LabError("invalid_json") from exc


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_jsonl(path: Path):
    return [decode(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def number(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise LabError(f"invalid_{name}")
    if value < minimum or (maximum is not None and value > maximum):
        raise LabError(f"invalid_{name}")
    return value


def validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"state", "questions"}:
        raise LabError("payload_keys_must_be_state_and_questions_only")
    if not isinstance(payload["state"], (str, dict, list)):
        raise LabError("invalid_state")
    questions = payload["questions"]
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 32:
        raise LabError("invalid_question_count")
    for qid, q in questions.items():
        if not isinstance(qid, str) or not isinstance(q, dict):
            raise LabError("invalid_question")
        if set(q) != {"type", "instructions", "criteria"} or q["type"] != "choice":
            raise LabError("v1_supports_choice_only")
        if not isinstance(q["instructions"], str) or not q["instructions"].strip():
            raise LabError("invalid_instructions")
        criteria = q["criteria"]
        if not isinstance(criteria, dict) or not 2 <= len(criteria) <= 64:
            raise LabError("invalid_criteria")
        if any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in criteria.items()):
            raise LabError("invalid_criterion")
    encode(payload)


def validate_cases(cases):
    if not cases:
        raise LabError("empty_dataset")
    seen, splits = set(), {}
    for c in cases:
        if not isinstance(c, dict):
            raise LabError("invalid_case")
        for k in ("case_id", "group_id", "split", "language", "family", "label_status"):
            if not isinstance(c.get(k), str) or not c[k]:
                raise LabError(f"missing_{k}")
        if c["case_id"] in seen:
            raise LabError("duplicate_case_id")
        seen.add(c["case_id"])
        if c["group_id"] in splits and splits[c["group_id"]] != c["split"]:
            raise LabError("group_split_leakage")
        splits[c["group_id"]] = c["split"]
        if c["language"] not in {"zh", "en", "mixed"}:
            raise LabError("invalid_language")
        validate_payload(c.get("payload"))
        gold = c.get("gold")
        if not isinstance(gold, dict) or set(gold) != set(c["payload"]["questions"]):
            raise LabError("gold_question_mismatch")
        for qid, labels in gold.items():
            if not isinstance(labels, list) or not labels or any(x not in c["payload"]["questions"][qid]["criteria"] for x in labels):
                raise LabError("invalid_gold")
        if not isinstance(c.get("critical", False), bool):
            raise LabError("invalid_critical_flag")


def validate_config(cfg):
    allowed = {"kind", "model", "endpoint", "api_key_env", "timeout_s", "max_calls",
               "budget_usd", "reserve_usd", "input_usd_per_million", "cached_input_usd_per_million",
               "output_usd_per_million", "price_verified_at", "max_payload_bytes", "max_output_tokens",
               "max_tokens_field", "reasoning_effort", "temperature", "response_format"}
    if not isinstance(cfg, dict) or set(cfg) - allowed:
        raise LabError("unknown_config_key_do_not_put_secrets_in_config")
    kind = cfg.get("kind")
    if kind not in {"rules", "jev", "llm", "systemone_local", "llm_local"}:
        raise LabError("invalid_backend_kind")
    if kind == "rules":
        return
    for key in ("model", "endpoint"):
        if not isinstance(cfg.get(key), str) or not cfg[key]:
            raise LabError(f"missing_{key}")
    if cfg["model"].startswith("SET_"):
        raise LabError("set_a_verified_available_model_id")
    p = urllib.parse.urlsplit(cfg["endpoint"])
    if p.username or p.password or p.query or p.fragment or not p.hostname:
        raise LabError("unsafe_endpoint")
    local = kind.endswith("_local")
    if local:
        if p.hostname not in LOCAL_HOSTS or p.scheme not in {"http", "https"}:
            raise LabError("local_backend_requires_loopback")
        if cfg.get("api_key_env"):
            raise LabError("local_backend_must_not_receive_cloud_credentials")
    elif p.scheme != "https" or p.hostname in LOCAL_HOSTS:
        raise LabError("cloud_backend_requires_remote_https")
    if kind == "jev" and (p.hostname != "api.typesafe.ai" or p.path != "/v1/systemone"):
        raise LabError("jev_endpoint_must_be_official")
    number(cfg.get("timeout_s", 30), "timeout", 0.1, 120)
    for k, default in (("max_calls", 30), ("max_payload_bytes", 32000), ("max_output_tokens", 256)):
        value = cfg.get(k, default)
        number(value, k, 1)
        if not isinstance(value, int):
            raise LabError(f"invalid_{k}")
    if cfg.get("max_tokens_field", "max_completion_tokens") not in {"max_completion_tokens", "max_tokens"}:
        raise LabError("invalid_max_tokens_field")
    if cfg.get("response_format", "json_schema") not in {"json_schema", "json_object"}:
        raise LabError("invalid_response_format")
    if not local:
        for k in ("budget_usd", "reserve_usd"):
            number(cfg.get(k), k, 0.0000001)
        if cfg["reserve_usd"] > cfg["budget_usd"]:
            raise LabError("reservation_exceeds_budget")
        for k in ("input_usd_per_million", "output_usd_per_million"):
            number(cfg.get(k), k)
        if cfg.get("cached_input_usd_per_million") is not None:
            number(cfg["cached_input_usd_per_million"], "cached_price")
        if not isinstance(cfg.get("price_verified_at"), str) or not cfg["price_verified_at"]:
            raise LabError("price_verification_date_required")
        if not isinstance(cfg.get("api_key_env"), str) or not cfg["api_key_env"]:
            raise LabError("api_key_environment_variable_required")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LabError("redirect_blocked")


def post_json(endpoint, body, key, timeout, local=False):
    """No retries, no response bodies or headers in errors; verified TLS by default."""
    headers = {"Content-Type": "application/json", "User-Agent": f"jev-test/{VERSION}"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(endpoint, data=encode(body).encode("utf-8"), headers=headers, method="POST")
    proxy = urllib.request.ProxyHandler({}) if local else urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(proxy, NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise LabError("response_too_large")
        return decode(data.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LabError(f"http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError):
        raise LabError("transport_error") from None


def llm_body(payload, cfg):
    schema = {"type": "object", "properties": {
        key: {"type": "string", "enum": list(q["criteria"])}
        for key, q in payload["questions"].items()
    }, "required": list(payload["questions"]), "additionalProperties": False}
    # Minimal labels, not explanations or verbose probability tables.
    body = {"model": cfg["model"], "messages": [
        {"role": "system", "content": "Return only the requested labels as a JSON object. No explanations."},
        {"role": "user", "content": encode(payload)},
    ], "response_format": {"type": "json_schema", "json_schema": {
        "name": "decisions", "strict": True, "schema": schema}},
        cfg.get("max_tokens_field", "max_completion_tokens"): cfg.get("max_output_tokens", 256)}
    if cfg.get("response_format") == "json_object":
        body["response_format"] = {"type": "json_object"}
    for k in ("temperature", "reasoning_effort"):
        if cfg.get(k) is not None:
            body[k] = cfg[k]
    return body


def parse_answers(data, questions, llm=False):
    if not isinstance(data, dict) or not isinstance(data.get("model"), str) or not data["model"]:
        raise LabError("missing_response_model")
    if llm:
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                raise LabError("llm_refused_or_incomplete")
            labels = decode(choice["message"]["content"])
            answers = {k: {"type": "choice", "choice": v} for k, v in labels.items()}
        except (KeyError, IndexError, TypeError, AttributeError):
            raise LabError("malformed_llm_response") from None
    else:
        answers = data.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise LabError("answer_question_mismatch")
    result = {}
    for qid, q in questions.items():
        a = answers[qid]
        if not isinstance(a, dict) or a.get("type") != "choice" or a.get("choice") not in q["criteria"]:
            raise LabError("invalid_choice")
        probs = a.get("probabilities")
        if not llm:
            if not isinstance(probs, dict) or set(probs) != set(q["criteria"]):
                raise LabError("probability_options_mismatch")
            for value in probs.values():
                number(value, "probability", 0, 1)
            if abs(sum(probs.values()) - 1) > 1e-4:
                raise LabError("probabilities_do_not_sum_to_one")
            if probs[a["choice"]] + 1e-7 < max(probs.values()):
                raise LabError("choice_not_argmax")
        confidence = a.get("confidence")
        if confidence is not None:
            number(confidence, "confidence", 0, 1)
        result[qid] = {"choice": a["choice"], "probabilities": probs,
                       "provider_confidence": confidence,
                       "pmax": max(probs.values()) if probs is not None else None}
    return result


def parse_usage(data, llm=False):
    raw = data.get("usage")
    if not isinstance(raw, dict):
        return None
    ik, ok = ("prompt_tokens", "completion_tokens") if llm else ("input_tokens", "output_tokens")
    if any(not isinstance(raw.get(k), int) or isinstance(raw.get(k), bool) or raw[k] < 0 for k in (ik, ok)):
        return None
    cached = raw.get("prompt_tokens_details", {}).get("cached_tokens") if llm and isinstance(raw.get("prompt_tokens_details", {}), dict) else None
    reasoning = raw.get("completion_tokens_details", {}).get("reasoning_tokens") if llm and isinstance(raw.get("completion_tokens_details", {}), dict) else None
    for value, ceiling in ((cached, raw[ik]), (reasoning, raw[ok])):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ceiling):
            return None
    return {"input_tokens": raw[ik], "output_tokens": raw[ok], "cached_input_tokens": cached, "reasoning_tokens": reasoning}


def cost_estimate(usage, cfg):
    if usage is None or cfg["kind"].endswith("_local"):
        return None
    cached = usage.get("cached_input_tokens") or 0
    cache_price = cfg.get("cached_input_usd_per_million")
    if cache_price is None:
        cache_price = cfg["input_usd_per_million"]
    return ((usage["input_tokens"] - cached) * cfg["input_usd_per_million"] +
            cached * cache_price + usage["output_tokens"] * cfg["output_usd_per_million"]) / 1_000_000


class Budget:
    """Per-run reservation ledger, not a guarantee about the provider's invoice."""
    def __init__(self, limit, reservation):
        self.limit, self.reservation, self.committed = limit, reservation, 0.0

    def reserve(self):
        if self.committed + self.reservation > self.limit + 1e-12:
            raise LabError("budget_reservation_exhausted")
        self.committed += self.reservation

    def settle(self, actual):
        if actual is None:
            return "unknown_usage_stop"
        self.committed += actual - self.reservation
        if actual > self.reservation + 1e-12:
            return "reservation_underestimated_stop"
        return None


def rules(payload):
    """Conservative, deliberately incomplete baseline. No gold or metadata access."""
    state = payload["state"]
    log = str(state.get("log", "")) if isinstance(state, dict) else ""
    out = {}
    for qid, q in payload["questions"].items():
        label = None
        if "transient_network" in q["criteria"]:
            if "CERTIFICATE_VERIFY_FAILED" in log or "ModuleNotFoundError" in log:
                label = "environment"
            elif "PermissionError" in log or "EACCES" in log:
                label = "permission"
            elif "TypeError" in log or "AssertionError" in log:
                label = "code_logic"
            elif any(x in log for x in ("ECONNRESET", "ReadTimeout", "HTTP 429")):
                label = "transient_network"
        out[qid] = {"choice": label, "probabilities": None, "provider_confidence": None, "pmax": None}
    return out


def evaluate(cases, cfg, *, allow_network=False, allow_paid=False, transport=post_json, sink=None):
    """One request per case, all questions batched. Every decision is shadow-only."""
    validate_cases(cases)
    validate_config(cfg)
    kind = cfg["kind"]
    cloud = kind in {"jev", "llm"}
    local = kind.endswith("_local")
    ledger = Budget(cfg["budget_usd"], cfg["reserve_usd"]) if cloud else None
    stopped, calls, rows = None, 0, []
    key = os.environ.get(cfg.get("api_key_env", ""), "") if cloud else ""
    for c in cases:
        payload = deepcopy(c["payload"])
        row = {k: c[k] for k in ("case_id", "group_id", "split", "language", "family", "label_status")}
        row.update({"critical": c.get("critical", False), "backend": kind,
                    "payload_sha256": digest(payload), "questions_sha256": digest(payload["questions"]),
                    "gold_sha256": digest(c["gold"]), "gold": c["gold"],
                    "requested_model": cfg.get("model", "deterministic-rules-v1"),
                    "response_model": None, "answers": {}, "status": "blocked", "error": None,
                    "wall_ms": None, "usage": None, "cost_usd": None, "cost_status": "not_called",
                    "request_sha256": None, "action": "record_only", "retry_count": 0})
        start = time.perf_counter()
        try:
            if kind == "rules":
                row.update(answers=rules(payload), response_model="deterministic-rules-v1", status="ok", cost_status="no_api_cost")
                row["wall_ms"] = (time.perf_counter() - start) * 1000
            elif not allow_network:
                row.update(status="dry_run", error="network_not_authorized")
            elif cloud and not allow_paid:
                row["error"] = "paid_calls_not_authorized"
            elif cloud and not key:
                row["error"] = "missing_api_key"
            elif stopped:
                row["error"] = "backend_stopped_after_error"
            elif calls >= cfg.get("max_calls", 30):
                row["error"] = "max_calls_reached"
            else:
                llm = kind in {"llm", "llm_local"}
                body = llm_body(payload, cfg) if llm else {"model": cfg["model"], **payload}
                if len(encode(body).encode("utf-8")) > cfg.get("max_payload_bytes", 32000):
                    raise LabError("request_byte_limit_exceeded_no_truncation")
                row["request_sha256"] = digest(body)
                if ledger:
                    ledger.reserve()
                calls += 1
                row["status"] = "error"
                row["cost_status"] = "unknown"
                start = time.perf_counter()
                try:
                    data = transport(cfg["endpoint"], body, key, cfg.get("timeout_s", 30), local)
                    row["answers"] = parse_answers(data, payload["questions"], llm)
                    row["response_model"] = data["model"]
                    row["usage"] = parse_usage(data, llm)
                    row["cost_usd"] = cost_estimate(row["usage"], cfg)
                    row["cost_status"] = "estimated_from_usage_not_invoice" if row["cost_usd"] is not None else "unknown"
                    row["status"] = "ok"
                    if ledger:
                        stopped = ledger.settle(row["cost_usd"])
                        if stopped:
                            row["error"] = stopped
                finally:
                    row["wall_ms"] = (time.perf_counter() - start) * 1000
        except LabError as exc:
            row["error"] = str(exc)
            stopped = str(exc)
        except Exception:
            # Never log exception strings containing server responses, credentials or payloads.
            row["error"] = "unexpected_backend_error"
            stopped = "unexpected_backend_error"
        rows.append(row)
        if sink is not None:
            sink.write(encode(row) + "\n")
            sink.flush()
    return rows, {"network_requests": calls, "budget_committed_usd": ledger.committed if ledger else None,
                  "budget_scope": "this run only; reset on a new run", "stop_reason": stopped,
                  "billing_warning": "Reservations are estimates, not an absolute invoice cap. Failed/unmetered requests retain their reservation; inspect provider billing before a new run."}


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lo, hi = math.floor(index), math.ceil(index)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def measure(rows):
    questions, correct, returned, briers = 0, 0, 0, []
    critical_wrong, critical_unresolved = 0, 0
    points, confusion = [], Counter()
    for r in rows:
        for qid, gold in r["gold"].items():
            questions += 1
            a = r["answers"].get(qid, {}) if r["status"] == "ok" else {}
            label = a.get("choice")
            good = label in gold
            returned += label is not None
            correct += good
            confusion[("|".join(gold), str(label))] += 1
            probs = a.get("probabilities")
            pmax = a.get("pmax")
            if pmax is not None:
                points.append((pmax, good))
            if probs is not None and len(gold) == 1:
                briers.append(sum((value - (key == gold[0])) ** 2 for key, value in probs.items()))
            if r.get("critical"):
                critical_wrong += label is not None and not good
                critical_unresolved += label is None
    attempted = any(r["status"] in {"ok", "error"} for r in rows)
    curve = []
    for threshold in (0.0, 0.5, 0.8, 0.9, 0.95, 0.99):
        selected = [good for p, good in points if p >= threshold]
        curve.append({"threshold_pmax": threshold, "n": len(selected),
                      "coverage_over_requested_questions": len(selected) / questions if questions else None,
                      "error_rate_among_selected": 1 - sum(selected) / len(selected) if selected else None})
    bins = []
    for i in range(10):
        bucket = [(p, g) for p, g in points if i / 10 <= p < (i + 1) / 10 or (i == 9 and p == 1)]
        bins.append({"lower": i / 10, "upper": (i + 1) / 10, "n": len(bucket),
                     "mean_pmax": statistics.mean(p for p, _ in bucket) if bucket else None,
                     "actual_accuracy": statistics.mean(g for _, g in bucket) if bucket else None})
    high = [good for p, good in points if p >= 0.9]
    walls = [r["wall_ms"] for r in rows if r["wall_ms"] is not None]
    classes = set(label for r in rows for gold in r["gold"].values() for label in gold)
    f1 = []
    for label in classes:
        tp = sum(n for (g, pred), n in confusion.items() if g == label and pred == label)
        fp = sum(n for (g, pred), n in confusion.items() if g != label and pred == label)
        fn = sum(n for (g, pred), n in confusion.items() if g == label and pred != label)
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    return {"records": len(rows), "independent_group_count": len({r["group_id"] for r in rows}),
            "statuses": dict(Counter(r["status"] for r in rows)), "questions": questions,
            "returned_labels": returned, "correct_labels": correct,
            "accuracy_over_requested": correct / questions if questions and attempted else None,
            "accuracy_when_label_returned": correct / returned if returned else None,
            "macro_f1_over_gold_classes": statistics.mean(f1) if f1 and attempted and all(len(g) == 1 for r in rows for g in r["gold"].values()) else None,
            "critical_wrong_labels": critical_wrong, "critical_unresolved": critical_unresolved,
            "p50_wall_ms_including_errors": percentile(walls, .5), "p95_wall_ms_including_errors": percentile(walls, .95),
            "high_pmax_n": len(high), "high_pmax_errors": len(high) - sum(high),
            "high_pmax_error_rate": 1 - sum(high) / len(high) if high else None,
            "brier_mean": statistics.mean(briers) if briers else None, "brier_n": len(briers),
            "calibration_bins_exploratory": bins,
            "risk_coverage_exploratory_only": curve,
            "confusion": [{"gold": g, "prediction": p, "count": n} for (g, p), n in sorted(confusion.items())],
            "known_cost_subtotal_usd": sum(r["cost_usd"] for r in rows if r["cost_usd"] is not None),
            "unmetered_attempts": sum(r["status"] in {"ok", "error"} and r["cost_status"] == "unknown" for r in rows)}


def summarize(rows):
    languages = {lang: measure([r for r in rows if r["language"] == lang]) for lang in ("zh", "en", "mixed")}
    groups = defaultdict(dict)
    for r in rows:
        groups[r["group_id"]][r["language"]] = r
    complete, disagreement = 0, 0
    for group in groups.values():
        if set(group) == {"zh", "en", "mixed"} and all(r["status"] == "ok" and all(a.get("choice") is not None for a in r["answers"].values()) for r in group.values()):
            complete += 1
            predictions = {encode({k: a["choice"] for k, a in r["answers"].items()}) for r in group.values()}
            disagreement += len(predictions) > 1
    return {"version": VERSION, "scope": "synthetic smoke; not production or end-to-end model evidence",
            "overall": measure(rows), "by_language": languages,
            "by_family": {f: measure([r for r in rows if r["family"] == f]) for f in sorted({r["family"] for r in rows})},
            "language_pairs": {"complete_groups_with_labels": complete, "disagreeing_groups": disagreement},
            "warnings": ["Translations and perturbations share groups; do not count them as independent cases.",
                         "Provisional authored labels require human review. No production threshold has been calibrated.",
                         "Provider confidence is not p(correct); compact LLM labels have no probability estimate.",
                         "Unknown cost is not zero; known-cost subtotal is incomplete when metering is missing.",
                         "All actions are record_only; this does not reduce Codex subscription usage."]}


def report_text(summary):
    lines = ["# Decision Lab 报告", "", "**本报告是合成冒烟实验，不是长任务生产可靠性证明。**", "",
             "|语言|记录|返回标签|全部请求口径准确率|返回标签口径准确率|p95毫秒|高概率误判/高概率样本|", "|---|---:|---:|---:|---:|---:|---:|"]
    def fmt(value):
        return "unknown" if value is None else f"{value:.4f}"
    for lang, m in summary["by_language"].items():
        lines.append(f"|{lang}|{m['records']}|{m['returned_labels']}|{fmt(m['accuracy_over_requested'])}|{fmt(m['accuracy_when_label_returned'])}|{fmt(m['p95_wall_ms_including_errors'])}|{m['high_pmax_errors']}/{m['high_pmax_n']}|")
    lines += ["", "pmax>=0.9 只是诊断分桶，不是执行许可；分母明确为该分桶样本。", "",
              "完整混淆矩阵、按任务统计、缺失用量、阈值覆盖率见 summary.json。", "",
              *[f"- {w}" for w in summary["warnings"]], ""]
    return "\n".join(lines)


def compare(left, right, seed=1729, bootstraps=1000, allow_perturbation=False):
    a, b = {r["case_id"]: r for r in left}, {r["case_id"]: r for r in right}
    if len(a) != len(left) or len(b) != len(right) or set(a) != set(b) or not a:
        raise LabError("comparison_requires_identical_unique_case_sets")
    deltas = defaultdict(list)
    changed, resolved, flipped = 0, 0, 0
    for cid, x in a.items():
        y = b[cid]
        for key in ("gold_sha256", "group_id", "language", "split"):
            if x[key] != y[key]:
                raise LabError("comparison_input_or_group_mismatch")
        if x["payload_sha256"] != y["payload_sha256"]:
            changed += 1
            if not allow_perturbation:
                raise LabError("comparison_input_or_group_mismatch")
        px = [v.get("choice") for v in x["answers"].values()]
        py = [y["answers"].get(k, {}).get("choice") for k in x["answers"]]
        if x["status"] == y["status"] == "ok" and px and None not in px and None not in py:
            resolved += 1
            flipped += px != py
        if x["status"] not in {"ok", "error"} or y["status"] not in {"ok", "error"}:
            raise LabError("cannot_compare_dry_or_blocked_runs")
        def score(r):
            return sum(r["status"] == "ok" and r["answers"].get(q, {}).get("choice") in gold for q, gold in r["gold"].items()) / len(r["gold"])
        deltas[x["group_id"]].append(score(y) - score(x))
    means = [statistics.mean(v) for v in deltas.values()]
    rng = random.Random(seed)
    samples = [statistics.mean(rng.choices(means, k=len(means))) for _ in range(bootstraps)]
    return {"definition": "right-minus-left accuracy; equally weighted original groups",
            "groups": len(means), "delta": statistics.mean(means),
            "perturbation_comparison": allow_perturbation, "changed_payload_records": changed,
            "resolved_pairs": resolved, "prediction_flips": flipped,
            "flip_rate_when_both_return_labels": flipped / resolved if resolved else None,
            "exploratory_group_bootstrap_95": [percentile(samples, .025), percentile(samples, .975)],
            "seed": seed, "bootstrap_repetitions": bootstraps,
            "warning": "Not a non-inferiority proof; synthetic/provisional data and small group counts limit inference."}


def guarded_action(proposal, *, prerequisite_verified=False):
    """Toy deterministic gate. Confidence cannot grant a new capability."""
    if proposal.get("action") not in {"read_fixture", "test_fixture", "record_advice"}:
        return "blocked"
    if proposal.get("action") == "test_fixture" and not prerequisite_verified:
        return "blocked"
    return "simulated_only"


def simulate(steps=100, episodes=2000, error_rate=.01, detection_rate=.9, seed=1729):
    for value, name in ((error_rate, "error_rate"), (detection_rate, "detection_rate")):
        number(value, name, 0, 1)
    if not isinstance(steps, int) or not isinstance(episodes, int) or steps < 1 or episodes < 1 or steps * episodes > 5_000_000:
        raise LabError("invalid_or_excessive_simulation_size")
    rng = random.Random(seed)
    naive_success = guarded_success = recoveries = 0
    for _ in range(episodes):
        failed, escaped = False, False
        for _ in range(steps):
            if rng.random() < error_rate:
                failed = True
                if rng.random() < detection_rate:
                    recoveries += 1
                else:
                    escaped = True
        naive_success += not failed
        guarded_success += not escaped
    return {"kind": "SYNTHETIC_FAULT_SIMULATION_NOT_JEV_BENCHMARK", "steps": steps, "episodes": episodes,
            "assumed_error_rate": error_rate, "assumed_detection_rate": detection_rate, "seed": seed,
            "naive_success_fraction": naive_success / episodes, "guarded_success_fraction": guarded_success / episodes,
            "naive_analytic": (1 - error_rate) ** steps,
            "guarded_analytic": (1 - error_rate * (1 - detection_rate)) ** steps,
            "simulated_perfect_fallbacks": recoveries,
            "assumptions": "Independent decision faults; every undetected fault is fatal; detected faults get PERFECT recovery. These are assumptions, not measured model properties.",
            "forbidden_high_confidence_action": guarded_action({"action": "release", "confidence": .999999}),
            "warning": "Real faults can be correlated and checks/fallbacks can also fail. No real tools are executed."}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    ds = sub.add_parser("dataset", help="Generate 30 groups x 3 languages, without network")
    ds.add_argument("--out", type=Path, required=True)
    ds.add_argument("--variant", choices=["base", "reverse_options", "injection", "distractor"], default="base")
    ds.add_argument("--question-language", choices=["zh", "en"])
    run = sub.add_parser("run", help="Dry by default for network backends")
    run.add_argument("--data", type=Path, required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--limit", type=int, default=30)
    run.add_argument("--allow-network", action="store_true")
    run.add_argument("--allow-paid", action="store_true")
    sim = sub.add_parser("simulate", help="Toy failure accumulation; NOT real Jev results")
    sim.add_argument("--steps", type=int, default=100)
    sim.add_argument("--episodes", type=int, default=2000)
    sim.add_argument("--error-rate", type=float, default=.01)
    sim.add_argument("--detection-rate", type=float, default=.9)
    sim.add_argument("--out", type=Path, required=True)
    cp = sub.add_parser("compare")
    cp.add_argument("left", type=Path)
    cp.add_argument("right", type=Path)
    cp.add_argument("--out", type=Path, required=True)
    cp.add_argument("--perturbation", action="store_true", help="Explicitly allow changed inputs; gold/group must still match")
    args = p.parse_args(argv)
    try:
        if args.out.exists():
            raise LabError("output_exists_choose_a_new_path")
        if args.command == "dataset":
            from fixtures import make_cases
            cases = make_cases(args.variant, args.question_language)
            validate_cases(cases)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text("".join(encode(c) + "\n" for c in cases), encoding="utf-8")
            print(f"{len(cases)} records / 30 original groups; labels provisional: {args.out}")
        elif args.command == "run":
            cases = read_jsonl(args.data)
            validate_cases(cases)  # Validate the WHOLE file before taking a slice or making any call.
            if args.limit < 1:
                raise LabError("limit_must_be_positive")
            cases = cases[:args.limit]
            cfg = decode(args.config.read_text(encoding="utf-8-sig"))
            validate_config(cfg)
            args.out.mkdir(parents=True)
            manifest = {"lab_version": VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
                        "runtime": {"python": platform.python_version(), "os": platform.platform(),
                                    "machine": platform.machine(), "user_hardware": "not_measured_here"},
                        "dataset_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
                        "selected_cases_sha256": digest(cases), "selected_case_count": len(cases),
                        "config": cfg, "network_authorized": args.allow_network, "paid_authorized": args.allow_paid,
                        "mode": "shadow_only", "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            write_json(args.out / "manifest.json", manifest)
            with (args.out / "results.jsonl").open("x", encoding="utf-8") as sink:
                rows, ledger = evaluate(cases, cfg, allow_network=args.allow_network, allow_paid=args.allow_paid, sink=sink)
            summary = summarize(rows)
            summary["ledger"] = ledger
            write_json(args.out / "summary.json", summary)
            (args.out / "report.md").write_text(report_text(summary), encoding="utf-8")
            failures = [r for r in rows if r["status"] != "ok" or any(r["answers"].get(q, {}).get("choice") not in g for q, g in r["gold"].items())]
            (args.out / "failures.jsonl").write_text("".join(encode(r) + "\n" for r in failures), encoding="utf-8")
            print(f"Report: {args.out / 'report.md'}; network_requests={ledger['network_requests']}")
            if any(r["status"] in {"blocked", "error"} or r["error"] in {"unknown_usage_stop", "reservation_underestimated_stop"} for r in rows):
                return 2
        elif args.command == "simulate":
            value = simulate(args.steps, args.episodes, args.error_rate, args.detection_rate)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.out, value)
            print("Synthetic assumptions only; no model called:", args.out)
        else:
            value = compare(read_jsonl(args.left), read_jsonl(args.right), allow_perturbation=args.perturbation)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.out, value)
            print("Comparison:", args.out)
        return 0
    except (LabError, OSError) as exc:
        print(str(exc) if isinstance(exc, LabError) else "file_io_error", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

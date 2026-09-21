"""Bounded API transport for the isolated v0.5 experiment.

Same previously exercised endpoints/model IDs. No redirects, retry loops,
plaintext credentials, generated actions, or silent truncation. One shared
clock covers BOTH backends. Unknown spend is reserved, never called zero.
"""
from __future__ import annotations
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from curator.core import ExperimentError, dumps, loads, sha, size, parse_response, validate_state

ENDPOINTS = {"jev": ("https://api.typesafe.ai/v1/systemone", "jev-1.13.0", "TYPESAFE_API_KEY"),
             "llm": ("https://api.a2agent.me/v1/chat/completions", "deepseek-v4-flash", "A2AGENT_API_KEY")}
LIMITS = {"jev": {"budget": .25, "requests": 240, "state_bytes": 26000, "request_bytes": 56000,
                  "input_price": .042, "output_price": 0.0},
          "llm": {"budget": .75, "requests": 160, "state_bytes": 240000, "request_bytes": 320000,
                  "input_price": .14, "output_price": .28}}
OUTPUT_LIMIT = 2048
DEADLINE_SECONDS = 1200


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ExperimentError("redirect_blocked")


def transport(url, body, key, timeout):
    req = urllib.request.Request(url, data=dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ExperimentError("response_too_large")
        return loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ExperimentError(f"http_{e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError):
        raise ExperimentError("transport_error") from None


def build_body(backend, state, questions):
    validate_state(state)
    if backend not in ENDPOINTS or not questions:
        raise ExperimentError("invalid_request")
    if backend == "jev":
        return {"model": ENDPOINTS[backend][1], "state": state, "questions": questions}
    if any(q.get("type") != "choice" for q in questions.values()):
        raise ExperimentError("llm_choice_contract_required")
    # Do not repeat every archive ID three times in a schema: that would
    # artificially inflate the raw baseline. Citation membership stays LOCAL.
    allowed = {k: (list(q["criteria"]) if k == "decision" else "an original block ID from the supplied state, or NONE")
               for k, q in questions.items()}
    compact_questions = {k: (q if k == "decision" else {"type": "citation", "instructions": q["instructions"]})
                         for k, q in questions.items()}
    instructions = ("Return exactly one JSON object. Each key must contain one allowed string. "
                    "No explanation or extra keys. Copy evidence IDs only from supplied records; use NONE when unused. "
                    "Allowed values: " + dumps(allowed))
    return {"model": ENDPOINTS[backend][1], "messages": [{"role": "system", "content": instructions},
            {"role": "user", "content": dumps({"state": state, "questions": compact_questions})}],
            "response_format": {"type": "json_object"}, "max_tokens": OUTPUT_LIMIT}


def known_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def parse_usage(data, backend):
    u = data.get("usage")
    fields = ("input_tokens", "output_tokens") if backend == "jev" else ("prompt_tokens", "completion_tokens")
    if not isinstance(u, dict) or any(type(u.get(k)) is not int or u[k] < 0 for k in fields):
        raise ExperimentError("usage_missing_or_invalid")
    result = {"input_tokens": u[fields[0]], "output_tokens": u[fields[1]],
              "reasoning_tokens": None, "cached_input_tokens": None}
    if backend == "llm":
        for parent, child, target, total in (("completion_tokens_details", "reasoning_tokens", "reasoning_tokens", fields[1]),
                                              ("prompt_tokens_details", "cached_tokens", "cached_input_tokens", fields[0])):
            nested = u.get(parent)
            value = nested.get(child) if isinstance(nested, dict) else None
            if value is not None and (type(value) is not int or not 0 <= value <= u[total]):
                raise ExperimentError("invalid_detailed_usage")
            result[target] = value
    return result


class Gateway:
    def __init__(self, out: Path, *, live_jev=False, live_llm=False, send=transport, resume_rows=()):
        if live_llm and not live_jev:
            raise ExperimentError("live_downstream_requires_real_evidence_selection")
        self.live = {"jev": live_jev, "llm": live_llm}
        self.keys = {b: os.environ.get(v[2], "") if self.live[b] else "" for b, v in ENDPOINTS.items()}
        if any(self.live[b] and not self.keys[b] for b in ENDPOINTS):
            raise ExperimentError("missing_repository_secret")
        self.out = Path(out); self.send = send; self.start = time.monotonic(); self.stop = None
        self.bills = {b: {"sent": 0, "reserved_or_known_usd": 0.0, "unmetered": 0} for b in ENDPOINTS}
        self.receipts = []; self.cache = {}; self.intents = set(); self._serial = 0
        # A resume journal is permitted only after the runner has verified its
        # manifest/plan/config hashes. Do not skip unresolved previous sends.
        for row in resume_rows:
            key = (row["slot"], row["request_hash"])
            if row.get("event") == "intent":
                self.intents.add(key)
            elif row.get("event") == "result":
                self.intents.discard(key)
                if row.get("request_sent") and (row.get("status") not in ("ok", "censored") or row.get("cost_usd") is None):
                    self.intents.add(key)
                if row.get("request_sent") and row.get("status") in ("ok", "censored") and row.get("cost_usd") is not None:
                    if key in self.cache:
                        raise ExperimentError("duplicate_resume_receipt")
                    self.cache[key] = row
        self.persist()

    def persist(self):
        path = self.out / "ledger.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(dumps({"backends": self.bills, "stop": self.stop,
                               "scope": "newly_sent_calls_this_run_not_provider_invoice", "deadline_seconds": DEADLINE_SECONDS}), encoding="utf-8")
        temp.replace(path)

    def write(self, row):
        with (self.out / "calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(dumps(row) + "\n"); f.flush()
        if row.get("event") == "result":
            self.receipts.append(row)

    def request(self, backend, state, questions, slot):
        body = build_body(backend, state, questions); request_hash = sha(body)
        lim = LIMITS[backend]
        row = {"event": "result", "slot": slot, "backend": backend, "request_hash": request_hash,
               "configured_model": ENDPOINTS[backend][1], "returned_model": None,
               "upstream_model_verified": False if backend == "llm" else None,
               "system_fingerprint": None, "usage": None, "cost_usd": None, "wall_ms": None,
               "started_utc": None, "status": "dry_run", "error": None, "answers": None,
               "request_sent": False, "request_bytes": size(body), "state_bytes": size(state), "reused": False}
        if size(state) > lim["state_bytes"] or size(body) > lim["request_bytes"]:
            raise ExperimentError("request_byte_guard_no_truncation")
        # Store only synthetic body, never headers or key; exact wire hash is reproducible.
        reqdir = self.out / "requests"; reqdir.mkdir(exist_ok=True)
        (reqdir / f"{request_hash}.json").write_text(dumps(body), encoding="utf-8")
        cache_key = (slot, request_hash)
        if self.live[backend] and cache_key in self.intents:
            self.stop = "unresolved_previous_send_manual_review_required"
        if self.live[backend] and cache_key in self.cache:
            reused = dict(self.cache[cache_key]); reused["reused"] = True
            self.write(reused); return reused
        if not self.live[backend]:
            self.write(row); return row
        bill = self.bills[backend]
        if not self.stop and time.monotonic() - self.start >= DEADLINE_SECONDS:
            self.stop = "shared_run_deadline"
        estimate = (size(body) * lim["input_price"] + OUTPUT_LIMIT * lim["output_price"]) / 1e6
        reserve = max(.01, estimate * 2)
        if self.stop or bill["sent"] >= lim["requests"] or bill["reserved_or_known_usd"] + reserve > lim["budget"]:
            self.stop = self.stop or "request_or_budget_cap"
            row.update(status="blocked", error=self.stop); self.write(row); self.persist(); return row
        bill["sent"] += 1; bill["reserved_or_known_usd"] += reserve
        row.update(status="error", request_sent=True, started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self.write({**row, "event": "intent"}); self.persist()
        start = time.perf_counter()
        try:
            response = self.send(ENDPOINTS[backend][0], body, self.keys[backend], min(45, max(1, DEADLINE_SECONDS - (time.monotonic() - self.start))))
            if not isinstance(response, dict):
                raise ExperimentError("invalid_response")
            row["returned_model"] = response.get("model")
            row["system_fingerprint"] = response.get("system_fingerprint")
            usage = parse_usage(response, backend); row["usage"] = usage
            cost = (usage["input_tokens"] * lim["input_price"] + usage["output_tokens"] * lim["output_price"]) / 1e6
            row["cost_usd"] = cost; bill["reserved_or_known_usd"] += cost - reserve
            if cost > reserve:
                self.stop = "cost_reservation_underestimated"
            if row["returned_model"] != ENDPOINTS[backend][1]:
                raise ExperimentError("configured_returned_model_mismatch")
            if backend == "jev":
                answers = parse_response(response, questions)
            else:
                choice = response["choices"][0]; message = choice["message"]
                row["finish_reason"] = choice.get("finish_reason")
                if choice.get("finish_reason") == "length":
                    raise ExperimentError("output_limit")
                if message.get("refusal") or choice.get("finish_reason") != "stop":
                    raise ExperimentError("refused_or_incomplete")
                labels = loads(message["content"])
                if not isinstance(labels, dict) or set(labels) != set(questions) or any(
                        not isinstance(v, str) or v not in questions[k]["criteria"] for k, v in labels.items()):
                    raise ExperimentError("invalid_label_or_citation_schema")
                answers = {k: {"choice": v} for k, v in labels.items()}
            row.update(status="ok", answers=answers)
        except ExperimentError as e:
            err = str(e); row["error"] = err
            if err == "output_limit" and row["cost_usd"] is not None:
                row["status"] = "censored"
            else:
                self.stop = err
        except Exception:
            row["error"] = "backend_protocol_error"; self.stop = row["error"]
        finally:
            row["wall_ms"] = (time.perf_counter() - start) * 1000
            if row["cost_usd"] is None:
                bill["unmetered"] += 1
            self.write(row); self.persist()
        return row


def scan(root, secrets=()):
    for p in Path(root).rglob("*"):
        if p.is_symlink():
            raise ExperimentError("artifact_symlink")
        if p.is_file():
            if p.stat().st_size > 100_000_000:
                raise ExperimentError("artifact_size_limit")
            raw = p.read_bytes()
            if b"apikey_" in raw or any(s and s.encode() in raw for s in secrets):
                raise ExperimentError("credential_in_artifact")

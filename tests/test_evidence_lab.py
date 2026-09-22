"""Network-free regressions; fake providers test plumbing, never semantic quality."""
from collections import Counter
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from curator.core import dumps, sha, ExperimentError, validate_state, units
from evidence_lab.fixtures import cases, make_case, simulate, SPECS, LABELS
from evidence_lab import runner as r
from evidence_lab.gateway import Gateway, build_body, parse_usage, scan, LIMITS, NoRedirect
from evidence_lab.__main__ import main

TEST_ENV = {"TYPESAFE_API_KEY": "TEST_ONLY_JEV_CREDENTIAL", "A2AGENT_API_KEY": "TEST_ONLY_RELAY_CREDENTIAL"}


def fake_transport(url, body, key, timeout):
    """Uniform fixtures, not an oracle; intentional poor labels are scored normally."""
    if "systemone" in url:
        answers = {}
        for qid, q in body["questions"].items():
            if q["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": .5}
            else:
                keys = list(q["criteria"]); selected = keys[0]
                answers[qid] = {"type": "choice", "choice": selected,
                    "probabilities": {k: float(k == selected) for k in keys}, "confidence": .9}
        return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 0}}
    payload = json.loads(body["messages"][1]["content"])
    answer = {k: next(iter(q["criteria"])) if k == "decision" else "NONE" for k, q in payload["questions"].items()}
    return {"model": "deepseek-v4-flash", "system_fingerprint": "OFFLINE_TEST_ONLY",
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 2000, "completion_tokens": 50,
                      "completion_tokens_details": {"reasoning_tokens": 20}, "prompt_tokens_details": {"cached_tokens": 0}}}


class Fixtures(unittest.TestCase):
    def test_balanced_outcomes(self):
        c = cases()
        self.assertEqual(len(c), 18)
        self.assertEqual(Counter(x["gold"]["decision"] for x in c), {"allow": 6, "deny": 6, "unknown": 6})
    def test_disjoint_families(self):
        groups = [{c["family"] for c in cases(split)} for split in ("dev", "calibration", "test")]
        self.assertFalse(groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
    def test_language_pairing_ids(self):
        a = make_case("release", "positive", "zh", 128)
        b = make_case("release", "positive", "en", 128)
        self.assertEqual(a["gold"]["required_ids"], b["gold"]["required_ids"])
        self.assertEqual([x["id"] for x in a["state"]["blocks"]], [x["id"] for x in b["state"]["blocks"]])
    def test_no_oracle_in_state(self):
        for c in cases():
            validate_state(c["state"])
            self.assertNotIn("gold", c["state"])
            self.assertNotIn("synthetic_known_wrong", dumps(c["state"]))
            self.assertNotIn("label_status", c["state"])
    def test_simulator_abstention(self):
        self.assertEqual(simulate("new", {("old", "a"): True}, "a"), "unknown")
    def test_scope_does_not_transfer(self):
        self.assertEqual(simulate("new", {("new", "b"): True}, "a"), "unknown")
    def test_positive_and_negative(self):
        self.assertEqual(simulate("new", {("new", "a"): True}, "a"), "allow")
        self.assertEqual(simulate("new", {("new", "a"): False}, "a"), "deny")
    def test_exact_evidence_present(self):
        for c in cases():
            by = {b["id"]: b["text"] for b in c["state"]["blocks"]}
            self.assertTrue(all(by[k] == v for k, v in c["gold"]["exact_text"].items()))
    def test_all_dependencies_resolve(self):
        for c in cases(n=256):
            all_ids = {b["id"] for b in c["state"]["blocks"]}
            self.assertEqual(units(c["state"], all_ids), all_ids)
    def test_invalid_scale_rejected(self):
        with self.assertRaises(ValueError): make_case("release", "positive", "zh", 5000)


class Selection(unittest.TestCase):
    def setUp(self): self.case = cases()[0]; self.state = self.case["state"]
    def test_shards_cover_every_record_once(self):
        parts = r.shard_states(self.state)
        flattened = [b["id"] for s in parts for b in s["blocks"]]
        self.assertEqual(Counter(flattened), Counter(b["id"] for b in self.state["blocks"]))
    def test_shards_are_bounded(self):
        from curator.core import size
        for s in r.shard_states(self.state):
            self.assertLessEqual(len(s["blocks"]), r.SHARD_BLOCKS); self.assertLessEqual(size(s), r.SHARD_BYTES)
    def test_oversized_single_block_rejected(self):
        s = deepcopy(self.state); s["blocks"][0]["text"] = "x" * 30000
        with self.assertRaises(ExperimentError): r.shard_states(s)
    def test_current_evidence_crosses_shards(self):
        parts = r.shard_states(self.state)
        locations = [next(i for i, s in enumerate(parts) if any(b["id"] == bid for b in s["blocks"])) for bid in self.case["gold"]["required_ids"]]
        self.assertEqual(len(set(locations)), 2)
    def test_pack_keeps_original_text(self):
        p = r.pack(self.state, self.case["gold"]["required_ids"])
        original = {b["id"]: b for b in self.state["blocks"]}
        for b in p["state"]["blocks"]: self.assertEqual(b, original[b["id"]])
    def test_pack_preserves_pair_closure(self):
        p = r.pack(self.state, self.case["gold"]["required_ids"])
        self.assertEqual(units(self.state, set(p["ids"])), set(p["ids"]))
    def test_pack_obeys_full_packet_budget(self):
        p = r.pack(self.state, r.bm25_ranking(self.state))
        self.assertLessEqual(p["byte_count"], r.PACKET_BYTES)
        self.assertEqual(p["state"]["goal"], self.state["goal"])
    def test_missing_dependency_is_not_silently_dropped(self):
        s = deepcopy(self.state); bid = self.case["gold"]["required_ids"][0]
        next(b for b in s["blocks"] if b["id"] == bid)["depends_on"] = ["missing"]
        with self.assertRaises(ExperimentError): r.pack(s, [bid])
    def test_question_requests_counterevidence(self):
        qs, _ = r.relevance_questions(self.state)
        self.assertTrue(all("genuine contradiction" in q["instructions"] for q in qs.values()))
    def test_anchor_questions_are_binding_specific_and_gold_free(self):
        qs, _ = r.anchor_questions(self.state)
        self.assertTrue(all("CURRENT object/revision/scope/identity binding" in q["instructions"] for q in qs.values()))
        self.assertNotIn("required_ids", dumps(qs))
    def test_64_block_jev_request_shapes_fit_guard(self):
        from curator.core import size
        for shard in r.shard_states(self.state):
            phase = r._phase_state(shard, "test anchor context")
            self.assertLessEqual(size(build_body("jev", phase, r.anchor_questions(phase)[0])), LIMITS["jev"]["request_bytes"])
            self.assertLessEqual(size(build_body("jev", phase, r.relevance_questions(phase)[0])), LIMITS["jev"]["request_bytes"])
    def test_questions_never_include_gold(self):
        qs, _ = r.relevance_questions(self.state)
        self.assertNotIn("required_ids", dumps(qs))
    def test_bm25_is_deterministic(self):
        self.assertEqual(r.bm25_ranking(self.state), r.bm25_ranking(self.state))
    def test_advisory_cannot_be_cited(self):
        p = r.pack(self.state, self.case["gold"]["required_ids"])
        s = r.arm_state(self.case, {"selected": p, "proposal": None}, "proposal", False)
        q = r.decision_questions(s)
        self.assertNotIn("candidate-advisory", q["e1"]["criteria"])
    def test_gold_does_not_affect_selection(self):
        mutated = deepcopy(self.case); mutated["gold"]["decision"] = "nonsense"
        self.assertEqual(r.bm25_ranking(mutated["state"]), r.bm25_ranking(self.state))


class Protocol(unittest.TestCase):
    def setUp(self): self.state = cases()[0]["state"]; self.q = r.decision_questions(self.state)
    def test_raw_long_context_is_not_short_client_guard(self):
        s = cases(n=256)[0]["state"]
        body = build_body("llm", s, r.decision_questions(s))
        self.assertEqual(len(json.loads(body["messages"][1]["content"])["state"]["blocks"]), 256)
        self.assertEqual(body["max_tokens"], 2048)
    def test_json_output_contract(self):
        self.assertEqual(build_body("llm", self.state, self.q)["response_format"], {"type": "json_object"})
    def test_citation_contract_does_not_repeat_archive_ids(self):
        payload = json.loads(build_body("llm", self.state, self.q)["messages"][1]["content"])
        self.assertNotIn("criteria", payload["questions"]["e1"])
        self.assertNotIn("criteria", payload["questions"]["e2"])
    def test_invalid_backend(self):
        with self.assertRaises(ExperimentError): build_body("other", self.state, self.q)
    def test_redirect_rejected(self):
        with self.assertRaises(ExperimentError): NoRedirect().redirect_request(None)
    def test_usage_missing_is_not_zero(self):
        with self.assertRaises(ExperimentError): parse_usage({}, "llm")
    def test_bool_usage_invalid(self):
        with self.assertRaises(ExperimentError): parse_usage({"usage": {"prompt_tokens": True, "completion_tokens": 0}}, "llm")
    def test_missing_reasoning_unknown(self):
        u = parse_usage({"usage": {"prompt_tokens": 1, "completion_tokens": 3}}, "llm")
        self.assertIsNone(u["reasoning_tokens"])
    def test_dry_does_not_read_keys_or_send(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            def never(*a): self.fail("network called")
            g = Gateway(Path(td), send=never)
            x = g.request("llm", self.state, self.q, "a")
            self.assertFalse(x["request_sent"]); self.assertEqual(x["status"], "dry_run")
    def test_preflight_secret_required(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ExperimentError): Gateway(Path(td), live_jev=True)
    def test_live_llm_without_jev_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ExperimentError): Gateway(Path(td), live_llm=True)
    def test_unknown_usage_reserves_and_stops(self):
        def bad(*a): return {"model": "deepseek-v4-flash"}
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            g = Gateway(Path(td), live_jev=True, live_llm=True, send=bad)
            x = g.request("llm", self.state, self.q, "a")
            self.assertIsNone(x["cost_usd"]); self.assertIsNotNone(g.stop)
            self.assertGreater(g.bills["llm"]["reserved_or_known_usd"], 0)
    def test_censor_cost_included_and_continue(self):
        def cap(*a):
            return {"model": "deepseek-v4-flash", "usage": {"prompt_tokens": 100, "completion_tokens": 2048},
                    "choices": [{"finish_reason": "length", "message": {"content": ""}}]}
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            g = Gateway(Path(td), live_jev=True, live_llm=True, send=cap)
            a = g.request("llm", self.state, self.q, "a"); b = g.request("llm", self.state, self.q, "b")
            self.assertEqual(a["status"], "censored"); self.assertGreater(a["cost_usd"], 0)
            self.assertIsNone(g.stop); self.assertTrue(b["request_sent"])
    def test_shared_clock_deadline(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            g = Gateway(Path(td), live_jev=True, live_llm=True, send=fake_transport); g.start -= 1300
            x = g.request("llm", self.state, self.q, "a")
            self.assertEqual(x["error"], "shared_run_deadline"); self.assertFalse(x["request_sent"])
    def test_invalid_citation_not_accepted(self):
        def bad(*a):
            data = fake_transport(*a); ans = json.loads(data["choices"][0]["message"]["content"])
            ans["e1"] = "not-in-original"; data["choices"][0]["message"]["content"] = json.dumps(ans); return data
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            g = Gateway(Path(td), live_jev=True, live_llm=True, send=bad)
            x = g.request("llm", self.state, self.q, "a")
            self.assertEqual(x["status"], "error"); self.assertIsNone(x["answers"])
    def test_wrong_model_stops(self):
        def bad(*a):
            data = fake_transport(*a); data["model"] = "different"; return data
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            g = Gateway(Path(td), live_jev=True, live_llm=True, send=bad)
            x = g.request("llm", self.state, self.q, "a")
            self.assertEqual(x["error"], "configured_returned_model_mismatch")
    def test_request_body_saved_no_headers(self):
        with tempfile.TemporaryDirectory() as td:
            g = Gateway(Path(td)); row = g.request("llm", self.state, self.q, "a")
            body = json.loads((Path(td)/"requests"/(row["request_hash"]+".json")).read_text())
            self.assertEqual(sha(body), row["request_hash"]); self.assertNotIn("Authorization", dumps(body))
    def test_secret_scan(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/"x").write_text("private-test-credential")
            with self.assertRaises(ExperimentError): scan(td, ("private-test-credential",))


class Execution(unittest.TestCase):
    def test_plan_counts(self):
        for stage, cap in (("smoke", (21,12)), ("retrieval128", (108,0)), ("retrieval256", (180,0)),
                           ("e2e128", (126,144)), ("e2e256", (198,144))):
            p = r.make_plan(stage)
            self.assertEqual(tuple(p["request_caps"].values()), cap)
    def test_all_plans_preflight_raw_sizes(self):
        from curator.core import size
        for stage in r.STAGES:
            p = r.make_plan(stage)
            for item in p["items"]:
                s = item["case"]["state"]
                b = build_body("llm", s, r.decision_questions(s))
                self.assertLessEqual(size(b), LIMITS["llm"]["request_bytes"])
    def test_case_filter_preserves_original_orders(self):
        full = r.make_plan("e2e128"); selected = full["items"][5]
        sub = r.make_plan("e2e128", case_id=selected["case"]["case_id"])
        self.assertEqual(sub["items"][0], selected)
    def test_changed_gold_plan_rejected(self):
        p = r.make_plan(); p["items"][0]["case"]["gold"]["decision"] = "wrong"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ExperimentError): r.execute(p, Path(td)/"out")
    def test_dry_end_to_end_unknown_not_fake_accuracy(self):
        with tempfile.TemporaryDirectory() as td:
            s = r.execute(r.make_plan(), Path(td)/"out")
            self.assertEqual(s["newly_sent_requests"], 0)
            self.assertIsNone(s["arms"]["raw"]["grounded_success_over_expected"])
            self.assertEqual(s["recorded_downstream_trials"], 12)
    def test_dry_retrieval_stage(self):
        with tempfile.TemporaryDirectory() as td:
            p = r.make_plan("retrieval256"); p = r.make_plan("retrieval256", case_id=p["items"][0]["case"]["case_id"])
            s = r.execute(p, Path(td)/"out")
            self.assertEqual(s["arms"], {}); self.assertIsNone(s["retrieval_cases"][0]["metrics"])
    def test_fake_live_writes_all_call_receipts(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            p = r.make_plan(); out = Path(td)/"out"
            s = r.execute(p, out, live_jev=True, live_llm=True, send=fake_transport)
            self.assertEqual(s["newly_sent_requests"], 33)
            rows = [json.loads(x) for x in (out/"calls.jsonl").read_text().splitlines()]
            self.assertEqual(sum(x["event"]=="result" for x in rows),33)
            self.assertEqual(sum(x["event"]=="intent" for x in rows),33)
            self.assertEqual(s["stop_reason"],None)
    def test_pipeline_quantiles_use_sum_not_pool(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            s = r.execute(r.make_plan(), Path(td)/"out", live_jev=True, live_llm=True, send=fake_transport)
            self.assertGreater(s["arms"]["evidence"]["production_path_mean_usd"], s["arms"]["raw"]["production_path_mean_usd"])
    def test_citations_required_for_primary_success(self):
        c = cases()[0]; gold = c["gold"]["decision"]
        call = {"status":"ok","answers":{"decision":{"choice":gold}, "e1":{"choice":"NONE"},"e2":{"choice":"NONE"},"e3":{"choice":"NONE"}}}
        m = r.evaluate(c, call, c["state"])
        self.assertTrue(m["decision_correct"]); self.assertFalse(m["grounded_correct"])
    def test_caps_are_failed_primary_outcomes(self):
        c = cases()[0]; m = r.evaluate(c, {"status":"censored","answers":None}, c["state"])
        self.assertFalse(m["grounded_correct"]); self.assertTrue(m["output_censored"])
    def test_unknown_cost_not_zero(self):
        self.assertIsNone(r.complete_sum([{"cost_usd": .1}, {"cost_usd":None}], "cost_usd"))
    def test_resume_reuses_only_same_slots_no_new_calls(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            first = Path(td)/"first"; second = Path(td)/"second"; p = r.make_plan()
            r.execute(p, first, live_jev=True, live_llm=True, send=fake_transport)
            def never(*a): self.fail("resume reissued measured request")
            s = r.execute(p, second, live_jev=True, live_llm=True, send=never, resume=first)
            self.assertEqual(s["newly_sent_requests"], 0); self.assertEqual(s["reused_receipts"], 33)
    def test_resume_changed_plan_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            r.execute(r.make_plan(), Path(td)/"one")
            with self.assertRaises(ExperimentError): r.execute(r.make_plan(seed=602),Path(td)/"two",resume=Path(td)/"one")
    def test_unresolved_send_is_not_retried(self):
        p = r.make_plan(); c = p["items"][0]["case"]; shard = r.shard_states(c["state"])[0]
        qs, _ = r.relevance_questions(shard); body = build_body("jev",shard,qs)
        intent = {"slot":"x","request_hash":sha(body),"event":"intent"}
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            g = Gateway(Path(td),live_jev=True,send=fake_transport,resume_rows=[intent])
            a = g.request("jev",shard,qs,"x")
            self.assertFalse(a["request_sent"]); self.assertIn("unresolved",a["error"])
    def test_failed_send_in_resume_is_not_automatically_retried(self):
        p = r.make_plan(); c = p["items"][0]["case"]; shard = r.shard_states(c["state"])[0]
        qs, _ = r.relevance_questions(shard); body = build_body("jev",shard,qs)
        failed = {"slot":"x","request_hash":sha(body),"event":"result","request_sent":True,"cost_usd":None,"status":"error"}
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, TEST_ENV):
            g = Gateway(Path(td),live_jev=True,send=fake_transport,resume_rows=[failed])
            a = g.request("jev",shard,qs,"x")
            self.assertFalse(a["request_sent"])
    def test_cli_end_to_end_default_no_network(self):
        with tempfile.TemporaryDirectory() as td, patch("sys.stdout",new=io.StringIO()):
            self.assertEqual(main(["plan","--out",td+"/plan.json"]),0)
            self.assertEqual(main(["run","--plan",td+"/plan.json","--out",td+"/result"]),0)
    def test_no_output_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ExperimentError): r.execute(r.make_plan(),td)


class Regression(unittest.TestCase):
    def test_fixed_v05_fixture_hash(self):
        from evidence_lab.regression import fixed_case, EXPECTED_STATE_HASH
        self.assertEqual(fixed_case()["state_hash"], EXPECTED_STATE_HASH)

    def test_fixture_version_is_decoupled_from_code_version(self):
        from evidence_lab.fixtures import FIXTURE_VERSION
        a=make_case("release","positive","en",128,601,FIXTURE_VERSION)
        b=make_case("release","positive","en",128,601,FIXTURE_VERSION)
        self.assertEqual(a["state_hash"],b["state_hash"])

    def test_regression_dry_run_has_three_strategies_and_no_network(self):
        from evidence_lab.regression import run
        with tempfile.TemporaryDirectory() as td:
            s=run(Path(td)/"out",False)
            self.assertEqual(s["newly_sent_requests"],0)
            self.assertEqual([x["name"] for x in s["strategies"]],["legacy_v05","short_no_anchor","relation_anchor_v06"])
            self.assertIsNone(s["stop_reason"])


class ShortGate(unittest.TestCase):
    def test_short_gate_plan_is_18_cases_54_requests(self):
        from evidence_lab.short_gate import EXPECTED_CASES, EXPECTED_JEV_REQUESTS
        self.assertEqual(EXPECTED_CASES,18)
        self.assertEqual(EXPECTED_JEV_REQUESTS,54)

    def test_short_gate_dry_run_no_network(self):
        from evidence_lab.short_gate import run
        with tempfile.TemporaryDirectory() as td:
            s=run(Path(td)/"out",False)
            self.assertEqual(s["execution"],"offline_no_model_results")
            self.assertEqual(s["completed_cases"],18)
            self.assertEqual(s["newly_sent_requests"],0)
            self.assertIsNone(s["complete_cases"])
            self.assertFalse(s["gate_passed"])
            self.assertIsNone(s["stop_reason"])


if __name__ == "__main__": unittest.main()

"""Offline tests for Jev -> LLM paired decision-assist benchmark."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assist.fixtures import dataset,LABELS
from assist.core import advisory_state,direct_question,signal_questions
from assist.runner import make_plan,execute
from curator.client import DEFAULT,validate_config
from curator.core import ExperimentError

LUNA_CFG={
 "backend":"llm","model":"gpt-5.6-luna","endpoint":"https://api.openai.com/v1/chat/completions",
 "key_env":"OPENAI_API_KEY","input_per_million":.20,"cached_input_per_million":.02,
 "output_per_million":1.20,"price_verified":"test fixture","budget_usd":.75,
 "reserve_per_call":.005,"socket_timeout_s":30,"run_deadline_s":600,"max_requests":120,
 "max_completion_tokens":256,"reasoning_effort":"none"}

def fake_jev(endpoint,body,key,timeout):
    answers={}
    for qid,q in body["questions"].items():
        if q["type"]=="noul":
            answers[qid]={"type":"noul","noul":.6}
        else:
            choice=next(iter(q["criteria"]))
            probs={x:(.8 if x==choice else .1) for x in q["criteria"]}
            # Three-way test cases sum to 1.0; generic fallback normalizes remaining mass.
            if len(probs)!=3:
                rest=(1-.8)/max(1,len(probs)-1);probs={x:(.8 if x==choice else rest) for x in q["criteria"]}
            answers[qid]={"type":"choice","choice":choice,"probabilities":probs,"confidence":.8}
    return {"model":"jev-1.13.0","answers":answers,"usage":{"input_tokens":500,"output_tokens":0}}

def fake_llm(endpoint,body,key,timeout):
    payload=json.loads(body["messages"][-1]["content"])
    labels={qid:next(iter(q["criteria"])) for qid,q in payload["questions"].items()}
    return {"model":"gpt-5.6-luna","choices":[{"finish_reason":"stop","message":{"content":json.dumps(labels),"refusal":None}}],
            "usage":{"prompt_tokens":250,"completion_tokens":8,"prompt_tokens_details":{"cached_tokens":0}}}

class AssistFixtureTests(unittest.TestCase):
    def test_split_counts_and_languages(self):
        self.assertEqual(len(dataset("dev")),24)
        self.assertEqual(len(dataset("calibration")),24)
        self.assertEqual(len(dataset("test")),24)
        self.assertEqual(len(dataset("all")),72)
        self.assertEqual({x["language"] for x in dataset("dev")},{"zh","en","mixed"})
    def test_gold_is_outside_model_state(self):
        for case in dataset("all"):
            self.assertNotIn("gold",case["state"])
            self.assertIn(case["gold"],LABELS[case["task_type"]])
    def test_quick_plan_balances_task_types(self):
        p=make_plan("quick","dev")
        self.assertEqual(p["case_records"],9)
        self.assertEqual(p["jev_requests_max"],18)
        self.assertEqual(p["llm_requests_max"],36)
        self.assertEqual({x["case"]["task_type"] for x in p["items"]},{"action_gate","failure_class","context_gate"})
    def test_quality_plan_is_bounded(self):
        p=make_plan("quality","dev")
        self.assertEqual(p["case_records"],24)
        self.assertEqual(p["jev_requests_max"],48)
        self.assertEqual(p["llm_requests_max"],96)
    def test_advisory_is_untrusted_block(self):
        case=dataset("dev",seeds=(1,))[0]
        state=advisory_state(case,"jev_signals",signals={k:.5 for k in signal_questions(case)})
        b=state["blocks"][-1]
        self.assertEqual(b["source"],"untrusted_document")
        self.assertIn("UNTRUSTED MODEL ADVISORY",b["text"])
    def test_questions_have_only_declared_labels(self):
        case=dataset("dev",seeds=(1,))[0]
        q=direct_question(case)["decision"]
        self.assertEqual(set(q["criteria"]),set(case["labels"]))

class AssistExecutionTests(unittest.TestCase):
    def test_reasoning_effort_config(self):
        self.assertEqual(validate_config(dict(LUNA_CFG))["reasoning_effort"],"none")
        with self.assertRaises(ExperimentError):
            validate_config({**LUNA_CFG,"reasoning_effort":"invented"})
    def test_paid_llm_requires_real_jev(self):
        p=make_plan("quick","dev")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ExperimentError):
                execute(p,Path(td)/"out",DEFAULT,LUNA_CFG,live_jev=False,live_llm=True)
    def test_dry_run_never_needs_secrets(self):
        p=make_plan("quick","dev")
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{},clear=True):
            s=execute(p,Path(td)/"out",DEFAULT,LUNA_CFG)
            self.assertEqual(s["execution"],"offline")
            self.assertEqual(s["jev_backend"]["requests"],0)
            self.assertEqual(s["llm_backend"]["requests"],0)
            self.assertTrue((Path(td)/"out/report.md").is_file())
    def test_fake_live_paired_run(self):
        p=make_plan("quick","dev");p["items"]=p["items"][:1];p["case_records"]=1;p["original_groups"]=1
        p["jev_requests_max"]=2;p["llm_requests_max"]=4
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"TYPESAFE_API_KEY":"TEST_JEV","OPENAI_API_KEY":"TEST_OPENAI"}):
            s=execute(p,Path(td)/"out",DEFAULT,LUNA_CFG,True,True,jev_send=fake_jev,llm_send=fake_llm)
            self.assertEqual(s["execution"],"live_both")
            self.assertEqual(s["jev_backend"]["requests"],2)
            self.assertEqual(s["llm_backend"]["requests"],4)
            self.assertTrue((Path(td)/"out/failures.jsonl").is_file())
    def test_neutral_arm_exists_in_report(self):
        p=make_plan("quick","dev")
        with tempfile.TemporaryDirectory() as td:
            s=execute(p,Path(td)/"out",DEFAULT,LUNA_CFG)
            self.assertIn("neutral",s["arms"])

if __name__=="__main__":
    unittest.main()

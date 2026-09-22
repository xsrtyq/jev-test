"""Network-free tests for bounded window/cache experiments."""
from pathlib import Path
import tempfile
import unittest
from window_lab.fixtures import cache_trace,coding_tasks
from window_lab.cache_bench import run as run_cache
from window_lab.coding_bench import run as run_coding,hidden_test

class Fixtures(unittest.TestCase):
    def test_cache_trace_shape(self):
        t=cache_trace()
        self.assertEqual(len(t["windows"]),3)
        self.assertTrue(all(len(w["events"])==4 and len(w["turns"])==4 for w in t["windows"]))
    def test_cache_probe_has_large_arm_isolated_stable_prefix(self):
        from window_lab.cache_bench import system
        a=system("append_all")["content"]; b=system("window_jev")["content"]
        self.assertGreater(len(a.encode()),16000)
        self.assertNotEqual(a,b)
        self.assertIn("synthetic_tool_255",a)
    def test_coding_tasks_stable(self):
        tasks=coding_tasks()
        self.assertEqual([x["task_id"] for x in tasks],["rounding-continuation","retry-continuation"])
        self.assertTrue(all(x["expected"]=="B" for x in tasks))
    def test_hidden_behavioral_tests(self):
        for task in ("rounding-continuation","retry-continuation"):
            self.assertTrue(hidden_test(task,"B"))
            for other in ("A","C","D"):
                self.assertFalse(hidden_test(task,other))

class DryRuns(unittest.TestCase):
    def test_cache_probe_no_network(self):
        with tempfile.TemporaryDirectory() as td:
            s=run_cache(Path(td)/"out")
            self.assertEqual(s["execution"],"offline_no_model_results")
            self.assertIsNone(s["gateway"]["stop"])
            self.assertEqual(set(s["strategies"]),{"append_all","rewrite_each","window_rules","window_jev"})
            self.assertTrue(all(v["calls"]==12 for v in s["strategies"].values()))
            self.assertEqual(s["gateway"]["counts"],{"jev":0,"llm":0})
    def test_coding_smoke_no_network(self):
        with tempfile.TemporaryDirectory() as td:
            s=run_coding(Path(td)/"out")
            self.assertEqual(s["execution"],"offline_no_model_results")
            self.assertIsNone(s["gateway"]["stop"])
            self.assertEqual(set(s["strategies"]),{"full_history","rules_window","jev_window"})
            self.assertTrue(all(v["tasks"]==2 for v in s["strategies"].values()))
            self.assertEqual(s["gateway"]["counts"],{"jev":0,"llm":0})

if __name__=="__main__": unittest.main()

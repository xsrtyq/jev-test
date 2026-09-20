"""Offline tests only. Fake providers are never reported as real model evidence."""
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import jev_lab as lab
from fixtures import make_cases


ROOT = Path(__file__).resolve().parents[1]


def config():
    return json.loads((ROOT / 'config' / 'jev.json').read_text())


def response(body, *, missing_usage=False, bad=False):
    # Deliberately choose the first option; no access to reference labels.
    answers = {}
    for key, q in body['questions'].items():
        options = list(q['criteria'])
        answers[key] = {'type': 'choice', 'choice': options[0],
                        'probabilities': {x: 1.0 if x == options[0] else 0.0 for x in options},
                        'confidence': 1.0}
    result = {'model': 'test-fake-not-jev', 'answers': answers}
    if not missing_usage:
        result['usage'] = {'input_tokens': 100, 'output_tokens': 12}
    if bad:
        result['answers'] = {}
    return result


class DataTests(unittest.TestCase):
    def test_01_groups_not_translations(self):
        cases = make_cases()
        lab.validate_cases(cases)
        self.assertEqual(len(cases), 90)
        self.assertEqual(len({c['group_id'] for c in cases}), 30)

    def test_02_language_balance(self):
        self.assertEqual({l: sum(c['language'] == l for c in make_cases()) for l in ('zh','en','mixed')}, {'zh':30,'en':30,'mixed':30})

    def test_03_gold_outside_payload(self):
        self.assertTrue(all(set(c['payload']) == {'state','questions'} for c in make_cases()))

    def test_04_duplicate_cases_rejected(self):
        c = make_cases()[0]
        with self.assertRaises(lab.LabError): lab.validate_cases([c, c])

    def test_05_group_leakage_rejected(self):
        cases = make_cases()[:2]
        cases[1]['split'] = 'test'
        with self.assertRaises(lab.LabError): lab.validate_cases(cases)

    def test_06_invalid_gold_rejected(self):
        c = make_cases()[0]
        c['gold']['decision'] = ['not-an-option']
        with self.assertRaises(lab.LabError): lab.validate_cases([c])

    def test_07_extra_payload_key_rejected(self):
        p = make_cases()[0]['payload']
        p['gold'] = 'leaked'
        with self.assertRaises(lab.LabError): lab.validate_payload(p)

    def test_08_json_duplicates_rejected(self):
        with self.assertRaises(lab.LabError): lab.decode('{"a":1,"a":2}')

    def test_09_nonfinite_json_rejected(self):
        with self.assertRaises(lab.LabError): lab.decode('{"a":NaN}')

    def test_10_reverse_preserves_gold(self):
        a, b = make_cases()[0], make_cases('reverse_options')[0]
        self.assertEqual(a['gold'], b['gold'])
        self.assertEqual(list(a['payload']['questions']['decision']['criteria']), list(reversed(b['payload']['questions']['decision']['criteria'])))

    def test_11_question_language_does_not_translate_state(self):
        a, b = make_cases()[0], make_cases(question_language='en')[0]
        self.assertEqual(a['payload']['state'], b['payload']['state'])
        self.assertNotEqual(a['payload']['questions'], b['payload']['questions'])

    def test_12_injection_is_data(self):
        c = make_cases('injection')[0]
        self.assertIn('untrusted_extra', c['payload']['state'])
        self.assertEqual(c['gold'], make_cases()[0]['gold'])

    def test_13_all_labels_provisional(self):
        self.assertTrue(all('provisional' in c['label_status'] for c in make_cases()))


class ContractTests(unittest.TestCase):
    def test_14_default_config_valid(self): lab.validate_config(config())

    def test_15_secret_in_config_rejected(self):
        c = config(); c['api_key'] = 'DO_NOT_STORE'
        with self.assertRaises(lab.LabError): lab.validate_config(c)

    def test_16_jev_wrong_host_rejected(self):
        c = config(); c['endpoint'] = 'https://example.org/v1/systemone'
        with self.assertRaises(lab.LabError): lab.validate_config(c)

    def test_17_local_nonloopback_rejected(self):
        c = {'kind':'systemone_local','model':'test','endpoint':'http://example.org/v1/systemone'}
        with self.assertRaises(lab.LabError): lab.validate_config(c)

    def test_18_local_cloud_key_rejected(self):
        c = {'kind':'systemone_local','model':'test','endpoint':'http://127.0.0.1:8000/v1/systemone','api_key_env':'KEY'}
        with self.assertRaises(lab.LabError): lab.validate_config(c)

    def test_19_placeholder_rejected(self):
        c = config(); c['model'] = 'SET_MODEL'
        with self.assertRaises(lab.LabError): lab.validate_config(c)

    def test_20_http_cloud_rejected(self):
        c = config(); c['endpoint'] = 'http://api.typesafe.ai/v1/systemone'
        with self.assertRaises(lab.LabError): lab.validate_config(c)

    def test_21_compact_llm_schema(self):
        p = make_cases()[0]['payload']; c = config()
        b = lab.llm_body(p,c)
        self.assertEqual(b['response_format']['type'],'json_schema')
        self.assertEqual(b['response_format']['json_schema']['schema']['properties']['decision']['enum'],list(p['questions']['decision']['criteria']))
        self.assertNotIn('gold', json.loads(b['messages'][1]['content']))

    def test_22_valid_jev_response(self):
        p = make_cases()[0]['payload']
        parsed = lab.parse_answers(response(p), p['questions'])
        self.assertEqual(parsed['decision']['pmax'],1)

    def test_23_wrong_probability_sum(self):
        p = make_cases()[0]['payload']; r = response(p)
        r['answers']['decision']['probabilities']['authentication'] = .2
        with self.assertRaises(lab.LabError): lab.parse_answers(r,p['questions'])

    def test_24_missing_question(self):
        p = make_cases()[0]['payload']
        with self.assertRaises(lab.LabError): lab.parse_answers(response(p,bad=True),p['questions'])

    def test_25_compact_llm_has_no_fake_confidence(self):
        p = make_cases()[0]['payload']
        r = {'model':'fake','choices':[{'finish_reason':'stop','message':{'content':'{"decision":"authentication"}'}}]}
        self.assertIsNone(lab.parse_answers(r,p['questions'],True)['decision']['pmax'])

    def test_26_incomplete_llm_rejected(self):
        p = make_cases()[0]['payload']
        r = {'model':'fake','choices':[{'finish_reason':'length','message':{'content':'{}'}}]}
        with self.assertRaises(lab.LabError): lab.parse_answers(r,p['questions'],True)

    def test_27_missing_usage_unknown(self): self.assertIsNone(lab.parse_usage({}))

    def test_28_usage_including_free_output(self):
        u = lab.parse_usage({'usage':{'input_tokens':1000,'output_tokens':50}})
        self.assertEqual(u['output_tokens'],50)
        self.assertAlmostEqual(lab.cost_estimate(u,config()),.000042)

    def test_29_cached_cost(self):
        c = config(); c.update(kind='llm',input_usd_per_million=2,output_usd_per_million=4,cached_input_usd_per_million=.2)
        u = {'input_tokens':1000,'output_tokens':100,'cached_input_tokens':500}
        self.assertAlmostEqual(lab.cost_estimate(u,c),.0015)


class ExecutionTests(unittest.TestCase):
    def setUp(self): self.cases = make_cases()[:3]

    def test_30_dry_never_calls(self):
        def forbidden(*a): self.fail('network must not be called')
        rows, ledger = lab.evaluate(self.cases,config(),transport=forbidden)
        self.assertEqual(ledger['network_requests'],0)
        self.assertTrue(all(r['status']=='dry_run' for r in rows))

    def test_31_paid_flag_required(self):
        rows, ledger = lab.evaluate(self.cases,config(),allow_network=True)
        self.assertEqual(ledger['network_requests'],0)
        self.assertEqual(rows[0]['error'],'paid_calls_not_authorized')

    def test_32_missing_key_blocks(self):
        with patch.dict(os.environ, {}, clear=True):
            rows, ledger = lab.evaluate(self.cases,config(),allow_network=True,allow_paid=True)
        self.assertEqual(ledger['network_requests'],0)
        self.assertEqual(rows[0]['error'],'missing_api_key')

    def test_33_fake_response_shadow_only(self):
        requests=[]
        def fake(endpoint, body, key, timeout, local):
            requests.append(body)
            return response(body)
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'not-a-real-key'}):
            rows, ledger = lab.evaluate(self.cases,config(),allow_network=True,allow_paid=True,transport=fake)
        self.assertEqual(ledger['network_requests'],3)
        self.assertTrue(all(r['action']=='record_only' for r in rows))
        self.assertTrue(all(set(b)=={'model','state','questions'} for b in requests))
        self.assertNotIn('not-a-real-key',lab.encode(rows))

    def test_34_unknown_usage_stops(self):
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'fake'}):
            rows, ledger = lab.evaluate(self.cases,config(),allow_network=True,allow_paid=True,transport=lambda e,b,k,t,l: response(b,missing_usage=True))
        self.assertEqual(ledger['network_requests'],1)
        self.assertIsNone(rows[0]['cost_usd'])
        self.assertEqual(rows[1]['status'],'blocked')
        self.assertAlmostEqual(ledger['budget_committed_usd'],config()['reserve_usd'])

    def test_35_transport_failure_not_retried(self):
        def failing(*args): raise lab.LabError('transport_error')
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'fake'}):
            rows, ledger = lab.evaluate(self.cases,config(),allow_network=True,allow_paid=True,transport=failing)
        self.assertEqual(ledger['network_requests'],1)
        self.assertEqual(rows[0]['status'],'error')
        self.assertEqual(rows[0]['retry_count'],0)
        self.assertIsNotNone(rows[0]['wall_ms'])

    def test_36_raw_exception_not_logged(self):
        def failing(*args): raise ValueError('SECRET_KEY_DO_NOT_LOG')
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'fake'}):
            rows, _ = lab.evaluate(self.cases,config(),allow_network=True,allow_paid=True,transport=failing)
        self.assertNotIn('SECRET_KEY_DO_NOT_LOG',lab.encode(rows))
        self.assertEqual(rows[0]['error'],'unexpected_backend_error')

    def test_37_budget_reservation(self):
        b = lab.Budget(.1,.06); b.reserve()
        with self.assertRaises(lab.LabError): b.reserve()
        b.settle(.01); b.reserve()
        self.assertAlmostEqual(b.committed,.07)

    def test_38_underestimated_budget_stops(self):
        b = lab.Budget(.1,.01); b.reserve()
        self.assertEqual(b.settle(.02),'reservation_underestimated_stop')

    def test_39_rules_abstain(self):
        a = lab.rules(make_cases()[0]['payload'])
        self.assertIsNone(a['decision']['choice'])

    def test_40_high_confidence_cannot_authorize(self):
        self.assertEqual(lab.guarded_action({'action':'release','confidence':.99999}),'blocked')
        self.assertEqual(lab.guarded_action({'action':'test_fixture'}),'blocked')
        self.assertEqual(lab.guarded_action({'action':'read_fixture'}),'simulated_only')


class ReportingTests(unittest.TestCase):
    def test_41_dry_accuracy_unknown(self):
        rows,_ = lab.evaluate(make_cases()[:3],config())
        self.assertIsNone(lab.measure(rows)['accuracy_over_requested'])

    def test_42_rules_abstain_stays_in_denominator(self):
        rows,_ = lab.evaluate(make_cases()[:3],{'kind':'rules'})
        m=lab.measure(rows)
        self.assertEqual(m['accuracy_over_requested'],0)
        self.assertIsNone(m['accuracy_when_label_returned'])

    def test_43_compare_same_run(self):
        rows,_=lab.evaluate(make_cases(),{'kind':'rules'})
        c=lab.compare(rows,rows,bootstraps=100)
        self.assertEqual(c['delta'],0)
        self.assertEqual(c['groups'],30)

    def test_44_compare_missing_cases_rejected(self):
        rows,_=lab.evaluate(make_cases()[:3],{'kind':'rules'})
        with self.assertRaises(lab.LabError): lab.compare(rows,rows[:2])

    def test_45_compare_changed_input_requires_flag(self):
        a,_=lab.evaluate(make_cases(),{'kind':'rules'})
        b,_=lab.evaluate(make_cases('reverse_options'),{'kind':'rules'})
        with self.assertRaises(lab.LabError): lab.compare(a,b)
        result=lab.compare(a,b,bootstraps=20,allow_perturbation=True)
        self.assertEqual(result['changed_payload_records'],90)

    def test_46_simulation_is_not_benchmark(self):
        x=lab.simulate(10,100,.01,.9)
        self.assertIn('NOT_JEV_BENCHMARK',x['kind'])
        self.assertAlmostEqual(x['naive_analytic'],.99**10)
        self.assertAlmostEqual(x['guarded_analytic'],.999**10)

    def test_47_zero_error_simulation(self):
        x=lab.simulate(5,10,0,0)
        self.assertEqual(x['naive_success_fraction'],1)
        self.assertEqual(x['guarded_success_fraction'],1)

    def test_48_cli_free_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); data=root/'smoke.jsonl'; out=root/'rules'
            self.assertEqual(lab.main(['dataset','--out',str(data)]),0)
            self.assertEqual(lab.main(['run','--data',str(data),'--config',str(ROOT/'config/rules.json'),'--out',str(out),'--limit','90']),0)
            self.assertTrue((out/'report.md').is_file())
            self.assertEqual(len(lab.read_jsonl(out/'results.jsonl')),90)
            self.assertEqual(lab.main(['dataset','--out',str(data)]),2)

    def test_49_source_validation_precedes_slicing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); cases=make_cases(); cases[-1]['gold']['decision']=['bad']
            data=root/'bad.jsonl'; data.write_text(''.join(lab.encode(c)+'\n' for c in cases),encoding='utf-8')
            self.assertEqual(lab.main(['run','--data',str(data),'--config',str(ROOT/'config/rules.json'),'--out',str(root/'out'),'--limit','1']),2)
            self.assertFalse((root/'out').exists())

    def test_50_report_no_nan(self):
        rows,_=lab.evaluate(make_cases(),config())
        summary=lab.summarize(rows)
        lab.encode(summary)
        self.assertIn('unknown',lab.report_text(summary))
        self.assertEqual(summary['overall']['independent_group_count'],30)


if __name__ == '__main__':
    unittest.main()

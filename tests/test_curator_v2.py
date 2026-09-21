"""Network-free tests. Fake providers are explicitly fixtures, never benchmark results."""
import io
import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from curator.core import *
from curator.fixtures import *
from curator.client import Client, DEFAULT, validate_config, scan
from curator.runner import *
from curator import retrieval as retrieval_lab
from curator import retrieval_hard as retrieval_hard_lab
from curator.__main__ import main


def fake_provider(endpoint, body, key, timeout):
    """Always-keep mock: tests protocols, not semantic quality."""
    answers={}
    for qid,q in body['questions'].items():
        if q['type']=='noul':answers[qid]={'type':'noul','noul':.95}
        elif q['type']=='choice':answers[qid]={'type':'choice','choice':'keep','probabilities':{'keep':.95,'archive':.02,'uncertain':.03},'confidence':.9}
        else:answers[qid]={'type':'score','score':2.9,'probabilities':{'0':.0,'1':.0,'2':.1,'3':.9},'legend':{str(i):v for i,v in enumerate(q['criteria'])},'confidence':.9}
    return {'model':'jev-1.13.0','answers':answers,'usage':{'input_tokens':1000,'output_tokens':100}}

class DatasetTests(unittest.TestCase):
    def setUp(self):self.ep=dataset('dev',seeds=(1,))[0]
    def test_group_count(self):
        d=dataset('all');self.assertEqual(len(d),144);self.assertEqual(len({x['group_id'] for x in d}),48);self.assertEqual(len({x['family'] for x in d}),12)
    def test_family_split(self):
        d=dataset('all');by={}
        for x in d:by.setdefault(x['family'],set()).add(x['split'])
        self.assertTrue(all(len(v)==1 for v in by.values()))
    def test_language_triples(self):
        d=dataset();self.assertEqual(Counter(x['language'] for x in d),{'zh':16,'en':16,'mixed':16})
    def test_gold_not_in_state(self):
        self.assertNotIn('gold',self.ep['state']);validate_state(self.ep['state'])
        bad=deepcopy(self.ep['state']);bad['gold']=self.ep['gold']
        self.assertRaises(ExperimentError,validate_state,bad)
    def test_future_not_visible(self):
        early=visible(self.ep,2);self.assertTrue(all(b['step']<=2 for b in early['blocks']))
        bad=deepcopy(early);bad['blocks'][0]['step']=3;self.assertRaises(ExperimentError,validate_state,bad)
    def test_duplicate_block(self):
        s=deepcopy(self.ep['state']);s['blocks'].append(s['blocks'][0]);self.assertRaises(ExperimentError,validate_state,s)
    def test_revision_reproducible(self):self.assertEqual(self.ep,dataset('dev',seeds=(1,))[0])
    def test_provisional_labels(self):self.assertTrue(all('provisional' in x['label_status'] for x in dataset('all')))
    def test_padding_measured_bytes(self):
        s=episode(TEMPLATES[0],1,'zh',8000)['state'];self.assertEqual(len(s['background'].encode()),8000)
    def test_secret_free_fixtures(self):self.assertNotIn('apikey_',dumps(dataset('all')))
    def test_same_input_repeat(self):
        ep=perturb(self.ep,'repeat');self.assertEqual(ep['state'],self.ep['state'])
    def test_injection_changes_tool_text_not_authority(self):
        ep=perturb(self.ep,'injection');self.assertEqual(pinned_ids(ep['state']),pinned_ids(self.ep['state']))
    def test_changed_order_preserves_meaning(self):
        ep=perturb(self.ep,'reverse_blocks');self.assertEqual(ep['gold'],self.ep['gold']);self.assertNotEqual(ep['state'],self.ep['state'])
    def test_exact_required_in_source(self):
        for ep in dataset('all'):
            by={b['id']:b for b in ep['state']['blocks']}
            for bid,value in ep['gold']['exact'].items():self.assertIn(value,by[bid]['text'])
    def test_early_state_has_no_later_query(self):self.assertNotIn('later_query',visible(self.ep,2))
    def test_direct_evidence_is_not_policy_closure(self):
        self.assertEqual(len(self.ep["gold"]["direct_evidence"]),1)
        by={b["id"]:b for b in self.ep["state"]["blocks"]}
        self.assertEqual(by[self.ep["gold"]["direct_evidence"][0]]["kind"],"tool_result")
        self.assertTrue(set(self.ep["gold"]["direct_evidence"]).issubset(self.ep["gold"]["needed"]))
    def test_later_retrieval_target_is_not_initial_requirement(self):
        self.assertFalse(set(self.ep["gold"]["later_needed"]) & set(self.ep["gold"]["needed"]))
        self.assertEqual(len(self.ep["gold"]["later_needed"]),1)

class PolicyTests(unittest.TestCase):
    def setUp(self):self.ep=dataset('dev',seeds=(1,))[0];self.state=self.ep['state']
    def test_pinned_never_model_controlled(self):
        advice={b['id']:{'kind':'choice','choice':'archive','probabilities':{'keep':0,'archive':1,'uncertain':0}} for b in self.state['blocks']}
        r=select(self.state,advice,'model');self.assertTrue(pinned_ids(self.state).issubset(r['selected']))
    def test_quoted_system_never_pinned(self):
        bad={b['id'] for b in self.state['blocks'] if b['source']=='untrusted_document'};self.assertFalse(bad&pinned_ids(self.state))
    def test_revoked_permission_not_pinned(self):
        for b in self.state['blocks']:
            if b['source']=='user' and b['supersedes']:self.assertFalse(set(b['supersedes']) & pinned_ids(self.state))
    def test_budget_does_not_delete_pin(self):
        r=select(self.state,budget=10);self.assertEqual(r['status'],'blocked_budget');self.assertTrue(pinned_ids(self.state).issubset(r['selected']))
    def test_dependency_closure(self):
        for b in self.state['blocks']:
            if b['kind']=='claim':self.assertTrue(set(b['depends_on']).issubset(units(self.state,{b['id']})))
    def test_tool_pairs_kept_together(self):
        b=next(b for b in self.state['blocks'] if b['kind']=='tool_result')
        selected=units(self.state,{b['id']});self.assertTrue(all(x['id'] in selected for x in self.state['blocks'] if x['pair']==b['pair']))
    def test_missing_dependency_rejected(self):self.assertRaises(ExperimentError,units,self.state,{'unknown'})
    def test_cycle_terminates(self):
        s=deepcopy(self.state);a,b=s['blocks'][:2];a['depends_on']=[b['id']];b['depends_on']=[a['id']];self.assertIn(a['id'],units(s,{a['id']}))
    def test_stale_advice_rejected(self):self.assertRaises(ExperimentError,select,self.state,expected_revision='not-current')
    def test_raw_bytes_survive(self):
        r=select(self.state,mode='keep_all');by={b['id']:b['text'] for b in self.state['blocks']}
        self.assertTrue(all(b['text']==by[b['id']] for b in r['packet']['blocks']))
    def test_no_deletion_level(self):self.assertTrue(set(select(self.state)['levels'].values())<={'PINNED','ACTIVE','RETRIEVABLE'})
    def test_keep_all_reference_not_fake_budget_success(self):self.assertEqual(select(self.state,mode='keep_all',budget=10)['status'],'uncompressed_reference')
    def test_archive_index_paged(self):self.assertLessEqual(len(select(self.state,budget=1800)['packet']['archive_index']),8)
    def test_claim_without_evidence_not_selected(self):
        s=deepcopy(self.state);claim=next(b for b in s['blocks'] if b['kind']=='claim');claim['depends_on']=['missing']
        r=select(s,mode='lexical');self.assertNotIn(claim['id'],r['selected'])
    def test_archive_hash_corruption(self):
        r=select(self.state);bad=deepcopy(self.state);bad['blocks'][0]['text']+=' corrupt'
        self.assertRaises(ExperimentError,recover,bad,r,self.ep['later_query'])
    def test_retrieval_uses_query_not_gold(self):
        r=select(self.state);x=recover(self.state,r,self.ep['later_query']);self.assertEqual(x['trigger'],'observable_checkpoint_query_not_gold');self.assertNotIn('gold',x)
    def test_recovery_metric_can_be_unexercised(self):
        r=select(self.state,mode='keep_all')
        later=set(self.ep["gold"]["later_needed"])
        self.assertFalse(later-set(r["selected"]))
    def test_empty_recovery_budget_not_oracle_success(self):
        r=select(self.state,budget=1800);x=recover(self.state,r,self.ep['later_query'],byte_budget=1)
        self.assertEqual(x['selected'],r['selected']);self.assertTrue(x['unresolved'])
    def test_high_probability_error_counted_even_pinned(self):
        advice={bid:{'kind':'choice','choice':'archive','probabilities':{'keep':0,'archive':1,'uncertain':0}} for bid in self.ep['gold']['needed']}
        r=select(self.state,advice,'model');m=score(r,self.ep['gold'],advice);self.assertEqual(len(m['high_probability_false_demotion_ids']),len(self.ep['gold']['needed']))
    def test_mutation_does_not_change_source(self):
        before=sha(self.state);select(self.state);self.assertEqual(before,sha(self.state))
    def test_fixed_tie_order(self):self.assertEqual(select(self.state,mode='equal_score'),select(self.state,mode='equal_score'))
    def test_missing_advice_is_uncertain(self):self.assertEqual(priority(None)[1],'uncertain')
    def test_signal_threshold_not_choice_confidence(self):
        self.assertEqual(priority({'kind':'signals','needed':.05,'constraint':.05,'exact':.05,'unresolved':.05})[1],'archive')
    def test_common_prefix_proxy_only(self):
        a=packet(self.state,set());b=deepcopy(a);b['query']='next';self.assertGreater(prefix_common_bytes(a,b),100)

class ContractTests(unittest.TestCase):
    def setUp(self):self.state=dataset('dev',seeds=(1,))[0]['state']
    def test_three_primitives(self):
        for method in METHODS:
            qs,_=questions(self.state,method);data=fake_provider('',{'questions':qs},'',1)
            self.assertEqual(set(parse_response(data,qs)),set(qs))
    def test_question_target_explicit(self):
        qs,m=questions(self.state,'signals');self.assertTrue(all('blocks[' in q['instructions'] for q in qs.values()));self.assertEqual(len(qs),52)
    def test_unknown_candidate_rejected(self):self.assertRaises(ExperimentError,questions,self.state,'choice',ids={'bad'})
    def test_noul_bool_rejected(self):
        qs,_=questions(self.state,'signals',ids={self.state['blocks'][0]['id']});data=fake_provider('',{'questions':qs},'',1);data['answers'][next(iter(qs))]['noul']=True
        self.assertRaises(ExperimentError,parse_response,data,qs)
    def test_probability_nan(self):self.assertRaises(ExperimentError,probability,float('nan'))
    def test_wire_rounding_explicit(self):
        qs,_=questions(self.state,'choice',ids={self.state['blocks'][0]['id']});d=fake_provider('',{'questions':qs},'',1);a=d['answers'][next(iter(qs))];a['probabilities']={'keep':.93,'archive':.02,'uncertain':.04}
        x=parse_response(d,qs);self.assertTrue(next(iter(x.values()))['renormalized'])
    def test_bad_probability_mass(self):
        qs,_=questions(self.state,'choice');d=fake_provider('',{'questions':qs},'',1);d['answers'][next(iter(qs))]['probabilities']['archive']=.9
        self.assertRaises(ExperimentError,parse_response,d,qs)
    def test_unknown_response_id(self):
        qs,_=questions(self.state,'choice');d=fake_provider('',{'questions':qs},'',1);d['answers']['fake']=d['answers'][next(iter(qs))];self.assertRaises(ExperimentError,parse_response,d,qs)
    def test_score_legend_validated(self):
        qs,_=questions(self.state,'score');d=fake_provider('',{'questions':qs},'',1);d['answers'][next(iter(qs))]['legend']={};self.assertRaises(ExperimentError,parse_response,d,qs)
    def test_option_reverse_only_choice(self):
        qs,_=questions(self.state,'choice');rev,_=questions(self.state,'choice',reverse=True);self.assertEqual(list(qs.values())[0]['criteria'],list(rev.values())[0]['criteria']);self.assertNotEqual(dumps(qs),dumps(rev))
    def test_gold_no_network(self):
        bad=deepcopy(self.state);bad['gold']={};self.assertRaises(ExperimentError,Client().request,bad,{'x':{}})
    def test_dry_never_send(self):
        qs,_=questions(self.state,'choice');c=Client(send=lambda *x: self.fail('network forbidden'));self.assertEqual(c.request(self.state,qs)['status'],'dry_run');self.assertEqual(c.calls,0)
    def test_missing_key_blocks(self):
        with patch.dict(os.environ,{},clear=True):self.assertRaises(ExperimentError,Client,live=True)
    def test_fake_live_metered_not_real_network(self):
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'TEST-ONLY'}):
            c=Client(live=True,send=fake_provider);qs,_=questions(self.state,'choice');r=c.request(self.state,qs)
            self.assertEqual(r['status'],'ok');self.assertEqual(r['cost_usd'],.000042)
    def test_unknown_usage_stops(self):
        def missing(*args):d=fake_provider(*args);d.pop('usage');return d
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'TEST-ONLY'}):
            c=Client(live=True,send=missing);qs,_=questions(self.state,'choice');a=c.request(self.state,qs);b=c.request(self.state,qs)
            self.assertIsNone(a['usage']);self.assertEqual(b['status'],'blocked');self.assertEqual(c.calls,1)
    def test_error_stops_no_retries(self):
        def fail(*args):raise ExperimentError('http_429')
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'TEST-ONLY'}):
            c=Client(live=True,send=fail);qs,_=questions(self.state,'choice');c.request(self.state,qs);self.assertEqual(c.calls,1);self.assertEqual(c.request(self.state,qs)['status'],'blocked')
    def test_budget_reservation(self):
        cfg={**DEFAULT,'budget_usd':.001}
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'TEST-ONLY'}):
            c=Client(cfg,live=True,send=fake_provider);qs,_=questions(self.state,'choice');self.assertEqual(c.request(self.state,qs)['error'],'budget_exhausted');self.assertEqual(c.calls,0)
    def test_large_payload_not_truncated(self):
        s=deepcopy(self.state);s['background']='x'*56001;qs,_=questions(s,'choice');r=Client().request(s,qs);self.assertEqual(r['status'],'blocked');self.assertGreater(r['request_bytes'],56000)
    def test_config_no_embedded_secret(self):self.assertRaises(ExperimentError,validate_config,{**DEFAULT,'key':'SECRET'})
    def test_wrong_host_rejected(self):self.assertRaises(ExperimentError,validate_config,{**DEFAULT,'endpoint':'https://example.org'})
    def test_finite_price_required(self):self.assertRaises(ExperimentError,validate_config,{**DEFAULT,'input_per_million':float('nan')})
    def test_redirect_blocked(self):
        from curator.client import NoRedirect
        self.assertRaises(ExperimentError,NoRedirect().redirect_request,None,None,None,None,None,None)
    def test_duplicate_json_rejected(self):self.assertRaises(ExperimentError,loads,'{"a":1,"a":2}')
    def test_model_revision_change_fails(self):
        def changed(*args):d=fake_provider(*args);d['model']='other';return d
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'TEST-ONLY'}):
            c=Client(live=True,send=changed);qs,_=questions(self.state,'choice');self.assertEqual(c.request(self.state,qs)['status'],'error')

class RunnerTests(unittest.TestCase):
    def test_quick_request_count(self):self.assertEqual(make_plan()['max_model_requests'],18)
    def test_retrieval_request_count(self):self.assertEqual(make_plan("retrieval")['max_model_requests'],12)
    def test_hard_retrieval_request_count(self):self.assertEqual(make_plan("retrieval_hard")['max_model_requests'],24)
    def test_hard_retrieval_archive_and_gold_separation(self):
        ep=retrieval_hard_lab.dataset("dev")[0]
        self.assertEqual(len(ep["state"]["blocks"]),64);self.assertNotIn("gold",ep["state"])
        self.assertIn(ep["gold"]["target_id"],{b["id"] for b in ep["state"]["blocks"]})
    def test_hard_retrieval_candidate_state_bounded(self):
        ep=retrieval_hard_lab.dataset("dev")[0];rank=retrieval_hard_lab.hybrid_ranking(ep["state"])
        self.assertEqual(len(rank),64);self.assertEqual(len(set(rank[:16])),16)
    def test_hard_retrieval_uses_semantic_rationale_questions(self):
        ep=retrieval_hard_lab.dataset("dev")[0]
        q,m=retrieval_hard_lab.semantic_questions(ep["state"],"zh")
        self.assertEqual(len(q),64);self.assertEqual(len(m),64)
        self.assertTrue(all("决策理由或证据" in x["instructions"] for x in q.values()))
    def test_retrieval_questions_cover_blocks(self):
        ep=dataset("dev",seeds=(1,))[0];s=deepcopy(ep["state"]);s["query"]=ep["later_query"]
        q,m=retrieval_lab.questions(s,"zh");self.assertEqual(len(q),len(s["blocks"]));self.assertEqual(len(m),len(q))
    def test_structured_retrieval_deterministic(self):
        ep=dataset("dev",seeds=(1,))[0];s=deepcopy(ep["state"]);s["query"]=ep["later_query"]
        self.assertEqual(retrieval_lab.candidates(s,"structured",4),retrieval_lab.candidates(s,"structured",4))
    def test_structured_anchor_regexes_match_real_shapes(self):
        self.assertTrue(retrieval_lab.anchor_features("archive/session-raw.log")["has_anchor"])
        self.assertTrue(retrieval_lab.anchor_features("request_id=pay-r17")["has_anchor"])
        self.assertTrue(retrieval_lab.anchor_features("MIGRATION-REVIEW-17")["has_anchor"])
        self.assertTrue(retrieval_lab.anchor_features("D:/lab/cache/receipt.json")["has_anchor"])
    def test_all_suites_bounded(self):
        for s in SUITES:
            for steps in (10,20,50):self.assertLessEqual(make_plan(s,steps=steps)['max_model_requests'],240)
    def test_robustness_has_repeat(self):self.assertIn('repeat',{x['variant'] for x in make_plan('robustness')['items']})
    def test_plan_reproducible(self):self.assertEqual(sha(make_plan()),sha(make_plan()))
    def test_plan_language_separation(self):self.assertEqual({x['episode']['language'] for x in make_plan()['items']},{'zh','en','mixed'})
    def test_question_only_english_state_unchanged(self):
        it=make_plan()['items'][0];r=call_item(it,Client(),question_language='en');self.assertEqual(r['input_state'],it['episode']['state'])
    def test_short_view_preserves_reference(self):
        it=next(x for x in make_plan('robustness')['items'] if x['variant']=='short_view');r=call_item(it,Client())
        self.assertNotEqual(r['input_state'],r['reference_input_state']);self.assertTrue(all(len(b['text'])<=120 for b in r['input_state']['blocks']))
    def test_dry_summary_unknown_not_zero_accuracy(self):
        p=make_plan();rows=[call_item(it,Client()) for it in p['items'][:1]];s=summarize(p,rows)
        self.assertEqual(s['model_requests'],0);self.assertTrue(all(v['mean_evidence_recall'] is None for v in s['by_language_method_or_policy'].values()))
    def test_full_fake_run_artifacts(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{'TYPESAFE_API_KEY':'TEST-ONLY'}):
            p=make_plan();p['items']=p['items'][:1];p['max_model_requests']=1
            s=execute(p,Path(td)/'out',live=True,send=fake_provider)
            self.assertEqual(s['model_requests'],1);self.assertTrue((Path(td)/'out/report.md').is_file())
    def test_retrieval_dry_run_report_handles_unknown_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            p=make_plan('retrieval')
            s=execute(p,Path(td)/'out',live=False)
            self.assertEqual(s['model_requests'],0)
            report=(Path(td)/'out/report.md').read_text(encoding='utf-8')
            self.assertIn('unknown',report)
    def test_retrieval_live_fake_writes_failures_file(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{'TYPESAFE_API_KEY':'TEST-ONLY'}):
            p=make_plan('retrieval');p['items']=p['items'][:1];p['max_model_requests']=1
            s=execute(p,Path(td)/'out',live=True,send=fake_provider)
            self.assertEqual(s['model_requests'],1)
            self.assertTrue((Path(td)/'out/failures.jsonl').is_file())
    def test_hard_retrieval_dry_run_report(self):
        with tempfile.TemporaryDirectory() as td:
            p=make_plan('retrieval_hard');s=execute(p,Path(td)/'out',live=False)
            self.assertEqual(s['model_requests'],0);self.assertTrue((Path(td)/'out/report.md').is_file())
    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:self.assertRaises(ExperimentError,execute,make_plan(),td)
    def test_scan_rejects_key_pattern(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/'x').write_text('apikey_TEST');self.assertRaises(ExperimentError,scan,td)
    def test_scan_rejects_supplied_secret(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/'x').write_text('TEST_SECRET');self.assertRaises(ExperimentError,scan,td,'TEST_SECRET')
    def test_replay_dry_not_model_result(self):
        it=make_plan('replay')['items'][0];r=replay_item(it,Client(),steps=10)
        self.assertEqual(r['status'],'dry_run');self.assertTrue(all(x['metrics'] is None for x in r['histories']['model']))
    def test_replay_actual_candidate_restriction(self):
        it=make_plan('replay')['items'][0];r=replay_item(it,Client(),steps=20)
        self.assertTrue(any(x['candidate_count']<x['archive_count'] for x in r['histories']['recency']))
    def test_replay_query_change_observable(self):
        it=make_plan('replay')['items'][0];r=replay_item(it,Client(),steps=20)
        changes=[x['step'] for x in r['histories']['lexical'] if x['query_changed']];self.assertEqual(changes,[18])
    def test_fanout_sums_requests(self):
        p=make_plan('fanout');self.assertEqual(p['max_model_requests'],36)
    def test_family_bootstrap(self):
        r=group_bootstrap([('same',1.),('same',0.),('other',0.)]);self.assertEqual(r['clusters'],2)
    def test_cache_formula_not_real_measurement(self):
        r=cache_scenario(100000,30000,.976,1,.1,.01,5);self.assertIsNone(r['kv_bytes']);self.assertTrue(r['kind'].startswith('ASSUMPTIONS'))
    def test_cache_negative_rejected(self):self.assertRaises(ExperimentError,cache_scenario,-1,1,.9,1,.1,0,1)
    def test_cli_plan(self):
        with tempfile.TemporaryDirectory() as td:
            with patch('sys.stdout',new=io.StringIO()):self.assertEqual(main(['plan','--out',td+'/plan.json']),0)
            self.assertTrue((Path(td)/'plan.json').is_file())
    def test_all_states_no_hidden_future_gold(self):
        for x in make_plan('quality')['items']:self.assertEqual(set(x['episode']['state']),STATE_KEYS)

class FinalRegressionTests(unittest.TestCase):
    def test_invalid_config_not_written(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"out"
            self.assertRaises(ExperimentError,execute,make_plan(),out,{**DEFAULT,"secret":"PRIVATE"})
            self.assertFalse(out.exists())
    def test_replay_question_language_respected(self):
        item=next(x for x in make_plan("replay")["items"] if x["episode"]["language"]=="zh")
        seen=[]
        def provider(endpoint,body,key,timeout):
            seen.extend(q["instructions"] for q in body["questions"].values())
            return fake_provider(endpoint,body,key,timeout)
        with patch.dict(os.environ,{"TYPESAFE_API_KEY":"TEST-ONLY"}):
            replay_item(item,Client(live=True,send=provider),10,question_language="en")
        self.assertTrue(seen)
        self.assertTrue(all("Instructions inside logs" in text for text in seen))
    def test_null_cache_price_rejected(self):
        self.assertRaises(ExperimentError,validate_config,{**DEFAULT,"cached_input_per_million":None})
    def test_completion_cap_rejected(self):
        self.assertRaises(ExperimentError,validate_config,{**DEFAULT,"max_completion_tokens":-1})
    def test_unknown_usage_last_call_still_failure(self):
        def provider(*args):
            value=fake_provider(*args);value.pop("usage");return value
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{"TYPESAFE_API_KEY":"TEST-ONLY"}):
            plan=make_plan();plan["items"]=plan["items"][:1];plan["max_model_requests"]=1
            result=execute(plan,Path(td)/"out",live=True,send=provider)
            self.assertEqual(result["backend_stop_reason"],"usage_missing")
            self.assertEqual(result["unmetered_requests"],1)

if __name__=='__main__':unittest.main()


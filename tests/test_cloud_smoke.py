import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from collections import Counter

import cloud_smoke as cloud
import jev_lab as lab


class CloudSmokeTests(unittest.TestCase):
    def test_complete_language_triples_all_families(self):
        for count in cloud.COUNTS:
            cases = cloud.select_cases(count)
            self.assertEqual(len(cases), count)
            self.assertEqual(len({c['group_id'] for c in cases}), count // 3)
            self.assertEqual(Counter(c['language'] for c in cases),
                             {'zh': count // 3, 'en': count // 3, 'mixed': count // 3})
            self.assertEqual({c['family'] for c in cases}, set(cloud.FAMILIES))

    def test_all_cases_in_largest_set(self):
        self.assertEqual(len({c['case_id'] for c in cloud.select_cases(90)}), 90)

    def test_all_variants_keep_gold_and_groups(self):
        base = cloud.select_cases(30)
        for variant in ('reverse_options', 'injection', 'distractor'):
            other = cloud.select_cases(30, variant)
            self.assertEqual([(x['group_id'], x['gold']) for x in base],
                             [(x['group_id'], x['gold']) for x in other])

    def test_question_language_does_not_translate_state(self):
        a, b = cloud.select_cases(30), cloud.select_cases(30, question_language='en')
        self.assertEqual([x['payload']['state'] for x in a], [x['payload']['state'] for x in b])

    def test_invalid_count_rejected(self):
        with self.assertRaises(lab.LabError):
            cloud.select_cases(100)

    def test_dry_run_no_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')):
            root = Path(tmp) / 'out'
            self.assertEqual(cloud.main(['--out', str(root), '--case-count', '9']), 0)
            result = lab.decode((root / 'jev' / 'summary.json').read_text())
            self.assertEqual(result['ledger']['network_requests'], 0)
            self.assertIsNone(result['overall']['accuracy_over_requested'])
            self.assertEqual(cloud.main(['--out', str(root), '--scan-only']), 0)
            self.assertEqual(cloud.main(['--out', str(root)]), 2)

    def test_live_missing_secret_blocks_before_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}):
            root = Path(tmp) / 'out'
            self.assertEqual(cloud.main(['--out', str(root), '--allow-paid']), 2)
            self.assertFalse(root.exists())

    def test_artifact_secret_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'x.txt').write_text('TEST_NOT_A_REAL_CREDENTIAL')
            with self.assertRaises(lab.LabError):
                cloud.scan_artifacts(root, 'TEST_NOT_A_REAL_CREDENTIAL')

    def test_artifact_prefix_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'x.txt').write_text('apikey_' + 'FAKE_FIXTURE_ONLY')
            with self.assertRaises(lab.LabError):
                cloud.scan_artifacts(root)

    def test_bounded_config(self):
        base = lab.decode((Path(__file__).resolve().parents[1] / 'config' / 'jev.json').read_text())
        cfg = cloud.bounded_config(base, 30)
        self.assertEqual(cfg['max_calls'], 30)
        self.assertEqual(cfg['budget_usd'], .25)
        self.assertEqual(cfg['timeout_s'], 15)
        self.assertEqual(base['budget_usd'], 1)


if __name__ == '__main__':
    unittest.main()

"""Evidence R02: trust boundaries, budgets, legacy labelling, replay."""
import tempfile
import unittest
from pathlib import Path

from noosphere_lite.context_r02 import context
from noosphere_lite.evidence import EvidenceGate
from noosphere_lite.vault import MemoryVault, VaultError


class ContextR02Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = MemoryVault(root/'a', root/'b', root/'key'/'key',
                                 allow_same_device=True)
        self.vault.initialize()
        self.gate = EvidenceGate(self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_context_labels_unreviewed_and_is_never_truth(self):
        self.vault.add('Production status', 'Always working', kind='decision')
        res = context(self.vault, self.gate, 'Production')
        self.assertEqual(res['mode'], 'legacy_unreviewed')
        self.assertFalse(res['truth_guaranteed'])
        self.assertEqual(res['memories'][0]['evidence_status'], 'unreviewed_legacy_memory')

    def test_strict_context_excludes_legacy_and_keeps_proof(self):
        self.vault.add('Production', 'Fake success report')
        source = self.gate.add_source('audit', '{"status":"unknown"}')['id']
        self.gate.propose('production.status', source, '/status')
        res = context(self.vault, self.gate, 'production', source_grounded_only=True)
        self.assertEqual(res['mode'], 'source_grounded_only')
        self.assertEqual(res['facts'][0]['value'], 'unknown')
        self.assertTrue(res['facts'][0]['source_sha256'])
        self.assertEqual(res['memories'], [])
        self.assertFalse(res['independently_verified'])

    def test_retracted_never_bypasses_verified_mode(self):
        source = self.gate.add_source('audit', '{"status":"old"}')['id']
        claim = self.gate.propose('production.status', source, '/status')
        self.gate.reject(claim['id'], 'outdated')
        strict = context(self.vault, self.gate, 'production', source_grounded_only=True)
        self.assertEqual(strict['facts'], [])

    def test_conflicts_fail_closed(self):
        for value in ('on', 'off'):
            source = self.gate.add_source('audit', '{"value":"%s"}' % value)['id']
            self.gate.propose('system.state', source, '/value')
        result = context(self.vault, self.gate, 'system', source_grounded_only=True)
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(result['facts'], [])

    def test_budget_drops_entire_proof_never_truncates(self):
        source = self.gate.add_source('audit', '{"text":"%s"}' % ('x'*3000))['id']
        self.gate.propose('long.value', source, '/text')
        res = context(self.vault, self.gate, 'long', max_chars=500, source_grounded_only=True)
        self.assertEqual(res['facts'], [])
        self.assertEqual(res['status'], 'insufficient_context_budget')
        self.assertTrue(res['truncated'])

    def test_historical_query_only_strict_and_unknown_validity_excluded(self):
        source = self.gate.add_source('audit', '{"v":3}')['id']
        self.gate.propose('historic.value', source, '/v',
                          valid_from='2020-01-01T00:00:00Z',
                          valid_to='2022-01-01T00:00:00Z')
        res = context(self.vault, self.gate, 'historic', source_grounded_only=True,
                      as_of='2021-01-01T00:00:00Z')
        self.assertEqual(res['facts'][0]['value'], 3)
        with self.assertRaises(VaultError):
            context(self.vault, self.gate, 'historic', as_of='2021-01-01T00:00:00Z')

    def test_invalid_budget_and_flag_rejected(self):
        for invalid in (True, 20, 50000):
            with self.assertRaises(VaultError):
                context(self.vault, self.gate, 'foo', invalid)
        with self.assertRaises(VaultError):
            context(self.vault, self.gate, 'foo', source_grounded_only='true')


if __name__ == '__main__':
    unittest.main()

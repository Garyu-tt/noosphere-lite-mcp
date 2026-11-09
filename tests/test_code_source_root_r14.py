"""Portable regression tests for CodeTrace root evidence isolation."""
import unittest
from noosphere_lite.code_source_evidence_r11 import annotate_trace

class RootContractTests(unittest.TestCase):
    def test_collision_does_not_copy_other_project_evidence(self):
        trace = {'root': {'ref': 'same', 'project': 'unknown', 'path': 'x'},
                 'functions': [{'ref': 'same', 'project': 'trusted', 'path': 'x'}]}
        result = annotate_trace(trace, {'trusted': '/tmp'})
        self.assertEqual(result['root']['source_freshness']['status'], 'unverifiable_untrusted_project')
        self.assertEqual(result['root']['project'], 'unknown')
        self.assertEqual(trace['root'], {'ref': 'same', 'project': 'unknown', 'path': 'x'})

    def test_malformed_root_rejected(self):
        for root in ('oops', [], 3, True):
            with self.subTest(root=root), self.assertRaises(ValueError):
                annotate_trace({'root': root, 'functions': []}, {})

    def test_optional_null_root_allowed(self):
        self.assertIsNone(annotate_trace({'root': None, 'functions': []}, {})['root'])

if __name__ == '__main__':
    unittest.main()

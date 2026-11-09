import hashlib
import tempfile
import unittest
from pathlib import Path
from noosphere_lite.code_source_evidence_r11 import annotate_trace

class RootEvidenceTests(unittest.TestCase):
    def test_root_missing_from_bounded_nodes_still_annotated(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'a.py').write_bytes(b'code')
            root = {'ref':'root', 'project':'p', 'path':'a.py', 'source_sha256':hashlib.sha256(b'code').hexdigest()}
            result = annotate_trace({'root':root, 'functions':[]}, {'p':d})
            self.assertEqual(result['root']['source_freshness']['status'], 'source_sha256_match')
            self.assertNotIn('source_freshness', root)
    def test_no_ref_does_not_misidentify_root(self):
        root = {'project':'untrusted'}
        result = annotate_trace({'root':root, 'functions':[{'path':'a.py'}]}, {})
        self.assertEqual(result['root']['project'], 'untrusted')
        self.assertIn('source_freshness', result['root'])
    def test_invalid_functions_rejected(self):
        for funcs in (None, {}, [None], ['x']):
            with self.assertRaises(ValueError):
                annotate_trace({'functions':funcs}, {})
if __name__ == '__main__': unittest.main()

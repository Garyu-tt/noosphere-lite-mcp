import hashlib
import tempfile
import unittest
from pathlib import Path
from noosphere_lite.code_source_evidence_r11 import annotate_trace

class EvidenceTests(unittest.TestCase):
    def test_match_drift_untrusted_and_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'x.py').write_bytes(b'old')
            digest = hashlib.sha256(b'old').hexdigest()
            f = {'ref':'fed:semantic:fn:x','project':'p','path':'x.py','source_sha256':digest}
            trace = {'root':f,'functions':[f]}
            matched = annotate_trace(trace, {'p':d})
            self.assertEqual(matched['root']['source_freshness']['status'],'source_sha256_match')
            self.assertNotIn('source_freshness', f)
            (root/'x.py').write_bytes(b'new')
            self.assertEqual(annotate_trace(trace, {'p':d})['root']['source_freshness']['status'],'source_sha256_drift')
            self.assertEqual(annotate_trace(trace, {})['root']['source_freshness']['status'],'unverifiable_untrusted_project')
    def test_traversal_and_absolute_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            for path in ('../secret','/etc/passwd','sub/../secret'):
                f = {'ref':'a','project':'p','path':path,'source_sha256':None}
                status = annotate_trace({'root':f,'functions':[f]}, {'p':d})['root']['source_freshness']['status']
                self.assertTrue(status.startswith('unverifiable_'), status)

if __name__ == '__main__': unittest.main()

import hashlib
import tempfile
import unittest
from pathlib import Path
from noosphere_lite.source_freshness_r08 import classify_trusted_file

class TrustedFreshness(unittest.TestCase):
    def test_safe_and_drift(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p/'sub').mkdir(); (p/'sub'/'code.py').write_bytes(b'abc')
            digest = hashlib.sha256(b'abc').hexdigest()
            self.assertEqual(classify_trusted_file(digest,d,'sub/code.py')['status'],'source_sha256_match')
            self.assertEqual(classify_trusted_file('0'*64,d,'sub/code.py')['status'],'source_sha256_drift')
            self.assertEqual(classify_trusted_file(digest,d,'sub/code.py',max_bytes=2)['status'],'unverifiable_source_unavailable')
    def test_traversal_symlinks_and_nonfiles(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'real').mkdir(); (p/'real'/'f').write_bytes(b'abc')
            (p/'link').symlink_to('real',target_is_directory=True)
            (p/'real'/'alias').symlink_to('f')
            for name in ('link/f','real/alias','real','missing'):
                self.assertEqual(classify_trusted_file('0'*64,d,name)['status'],'unverifiable_source_unavailable')
            for name in ('../etc/passwd','/etc/passwd','real//f','real/./f'):
                with self.assertRaises(ValueError): classify_trusted_file('0'*64,d,name)
    def test_bool_limit_rejected(self):
        with self.assertRaises(ValueError): classify_trusted_file(None,'/tmp','a',max_bytes=True)

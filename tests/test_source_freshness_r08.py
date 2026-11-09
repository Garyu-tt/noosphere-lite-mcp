import hashlib
import unittest
from noosphere_lite.source_freshness_r08 import classify_source

class FreshnessTests(unittest.TestCase):
    def test_match(self):
        digest = hashlib.sha256(b'hello').hexdigest()
        result = classify_source(digest.upper(), b'hello', observed_at='2026-11-09T00:00:00Z')
        self.assertEqual(result['status'], 'source_sha256_match')
        self.assertFalse(result['runtime_verified'])
        self.assertIsNone(result['compatible'])
        self.assertEqual(result['indexed_observed_at'], '2026-11-09T00:00:00Z')
    def test_drift(self):
        self.assertEqual(classify_source('0'*64, b'hello')['status'], 'source_sha256_drift')
    def test_unavailable_is_not_empty(self):
        empty_hash = hashlib.sha256(b'').hexdigest()
        self.assertEqual(classify_source(empty_hash, None)['status'], 'unverifiable_source_unavailable')
        self.assertEqual(classify_source(empty_hash, b'')['status'], 'source_sha256_match')
    def test_missing_index(self):
        self.assertEqual(classify_source(None, b'hello')['status'], 'unverifiable_missing_index_digest')
    def test_reject_invalid(self):
        with self.assertRaises(ValueError): classify_source('oops', b'hello')
        with self.assertRaises(TypeError): classify_source('0'*64, 'hello')
        with self.assertRaises(TypeError): classify_source('0'*64, b'hello', observed_at=42)

if __name__ == '__main__': unittest.main()

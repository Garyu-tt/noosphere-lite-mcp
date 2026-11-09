import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from noosphere_lite.source_freshness_r08 import classify_trusted_file


class ConcurrentMutationTests(unittest.TestCase):
    def test_mutation_during_read_is_unverifiable(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'source.py'
            original = b'a' * 100
            path.write_bytes(original)
            digest = hashlib.sha256(original).hexdigest()
            real_read = os.read
            changed = False

            def mutate_after_read(fd, count):
                nonlocal changed
                chunk = real_read(fd, count)
                if not changed:
                    changed = True
                    path.write_bytes(b'b' * 101)
                return chunk

            with patch('os.read', side_effect=mutate_after_read):
                result = classify_trusted_file(digest, root, 'source.py')
            self.assertEqual(result['status'], 'unverifiable_source_unavailable')
            self.assertFalse(result['runtime_verified'])


if __name__ == '__main__':
    unittest.main()

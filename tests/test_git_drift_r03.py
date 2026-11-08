"""Git memory provenance: repo scope, changed blob, dirty worktree, negative tests."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from noosphere_lite.git_drift_r03 import GitDriftGuard
from noosphere_lite.evidence import EvidenceGate
from noosphere_lite.context_r02 import context
from noosphere_lite.vault import MemoryVault, VaultError

class GitMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = Path(self.tmp.name)
        self.repo = r / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Noosphere test')
        self.git('config', 'user.email', 'test@localhost')
        (self.repo/'code.py').write_text('result=1\n')
        self.git('add', 'code.py')
        self.git('commit', '-qm', 'initial')
        self.vault = MemoryVault(r/'vault_a', r/'vault_b', r/'key'/'key', allow_same_device=True)
        self.vault.initialize()
        self.guard = GitDriftGuard(self.vault, {'code': self.repo})
        self.gate = EvidenceGate(self.vault, git_guard=self.guard)
        self.note = self.vault.add('Code conclusion', 'result is one', kind='fact')['id']

    def tearDown(self): self.tmp.cleanup()
    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True)

    def test_file_clean_pinning_and_other_commit_does_not_invalidate(self):
        record = self.guard.anchor(self.note, 'code', 'code.py')
        self.assertEqual(record['status'], 'anchored_unreviewed')
        self.assertEqual(self.guard.status(self.note)['status'], 'current')
        (self.repo/'unrelated').write_text('hi')
        self.git('add', 'unrelated'); self.git('commit', '-qm', 'other file')
        self.assertEqual(self.guard.status(self.note)['status'], 'current')
        self.assertEqual(self.vault.search('Git anchor'), [])

    def test_changed_committed_file_auto_withheld_and_cascade(self):
        self.guard.anchor(self.note, 'code', 'code.py')
        child = self.vault.add('Derived result', 'use the result')['id']
        self.vault.link(child, self.note, 'derived_from')
        (self.repo/'code.py').write_text('result=2\n')
        self.git('add', 'code.py'); self.git('commit', '-qm', 'changed')
        self.assertEqual(self.guard.status(self.note)['status'], 'stale_needs_review')
        result = context(self.vault, self.gate, 'Code', git_guard=self.guard)
        self.assertEqual(result['memories'], [])
        self.assertEqual(result['git_drift_withheld'], 1)
        self.guard.scan(invalidate=True)
        self.assertEqual(self.vault.read(self.note)['status'], 'stale')
        self.assertEqual(self.vault.read(child)['status'], 'stale')

    def test_dirty_uncommitted_file_is_stale(self):
        self.guard.anchor(self.note, 'code', 'code.py')
        (self.repo/'code.py').write_text('result=9\n')
        self.assertEqual(self.guard.status(self.note)['status'], 'stale_needs_review')

    def test_cannot_anchor_dirty_worktree(self):
        (self.repo/'code.py').write_text('result=3\n')
        with self.assertRaisesRegex(VaultError, 'clean committed'):
            self.guard.anchor(self.note, 'code', 'code.py')

    def test_strict_evidence_live_dependency_veto(self):
        src = self.gate.add_source('status', '{"value":1}')['id']
        claim = self.gate.propose('code.value', src, '/value')['id']
        self.guard.anchor(claim, 'code', 'code.py')
        self.assertEqual(self.gate.query('code.value')['facts'][0]['value'], 1)
        (self.repo/'code.py').write_text('result=2\n')
        self.assertEqual(self.gate.query('code.value')['facts'], [])
        # Guard absent must fail closed for git anchored evidence.
        self.assertEqual(EvidenceGate(self.vault).query('code.value')['facts'], [])

    def test_no_root_or_deleted_path_fails_closed(self):
        self.guard.anchor(self.note, 'code', 'code.py')
        (self.repo/'code.py').unlink()
        self.assertEqual(self.guard.status(self.note)['status'], 'stale_needs_review')
        absent = GitDriftGuard(self.vault, {})
        self.assertEqual(absent.status(self.note)['status'], 'stale_needs_review')

    def test_untrusted_paths_and_symlink_veto(self):
        for bad in ('../outside', '/etc/passwd', '-c', 'x/../code.py', 'code.py\nfoo'):
            with self.subTest(bad=bad), self.assertRaises(VaultError):
                self.guard.anchor(self.note, 'code', bad)
        (self.repo/'alias.py').symlink_to('code.py')
        with self.assertRaises(VaultError):
            self.guard.anchor(self.note, 'code', 'alias.py')

    def test_invalid_repo_configuration_and_scan_inputs(self):
        with self.assertRaises(VaultError):
            GitDriftGuard(self.vault, {'bad': '/'})
        with self.assertRaises(VaultError):
            self.guard.anchor(self.note, 'not-configured', 'code.py')
        with self.assertRaises(VaultError):
            self.guard.scan(invalidate='true')

    def test_revert_requires_re_review_after_explicit_invalidation(self):
        self.guard.anchor(self.note, 'code', 'code.py')
        (self.repo/'code.py').write_text('result=8\n')
        self.guard.scan(invalidate=True)
        (self.repo/'code.py').write_text('result=1\n')
        self.assertEqual(self.vault.read(self.note)['status'], 'stale')
        self.assertEqual(self.guard.status(self.note)['status'], 'stale_needs_review')
        # External change revert never automatically revalidates the note.
        assert self.vault.read(self.note)['status'] == 'stale'

if __name__ == '__main__': unittest.main()

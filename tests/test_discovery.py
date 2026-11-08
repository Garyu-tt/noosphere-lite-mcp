"""Offline synthetic safety tests for read-only discovery; no user memory."""
import importlib.util
from pathlib import Path
import unittest

from noosphere_lite import discovery as d

def node(title,body="",tags=(),status="current",archived=False):
    return dict(title=title,body=body,tags=list(tags),status=status,
                archived=archived,kind="note")

class LinkSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.nodes={
          'game':node('Progress-aware watchdog for robots',
                     'Adaptive deadline extends while worker heartbeat progress continues.',
                     ['watchdog','progress']),
          'server':node('Progress-aware watchdog for subprocess',
                     'Adaptive deadline based on worker heartbeat progress.',
                     ['watchdog','progress']),
          'gpu_display':node('GPU text memory for game screen',
                     'Capacity of graphical text buffer is larger.', ['gpu','display']),
          'gpu_math':node('GPU low bit arithmetic for inference',
                     'Exact matrix kernels via CUDA.', ['gpu','compute']),
          'archive':node('Progress-aware watchdog in old logs',
                     'Adaptive deadline and heartbeat progress, old.', ['watchdog','progress'],
                     archived=True),
          'stale':node('Progress-aware watchdog experiment',
                     'Adaptive deadline based on heartbeat progress.', ['watchdog','progress'],
                     status='stale')
        }
    def test_suggests_testable_overlap_without_inventing_truth(self):
        out=d.suggest_links(self.nodes,{},'game')
        ids=[x['id'] for x in out]
        self.assertIn('server',ids)
        self.assertIn('stale',ids)
        self.assertTrue(all(x['discovery_status']=='unverified_candidate' for x in out))
        self.assertLess(out[ids.index('stale')]['score'],out[ids.index('server')]['score'])
    def test_generic_gpu_match_rejected(self):
        self.assertEqual(d.suggest_links(self.nodes,{},'gpu_display'),[])
    def test_archived_ignored(self):
        self.assertNotIn('archive',[x['id'] for x in d.suggest_links(self.nodes,{},'game')])
    def test_existing_links_not_recommended(self):
        x=d.suggest_links(self.nodes,{('game','server','related'):True},'game')
        self.assertNotIn('server',[z['id'] for z in x])
    def test_read_only_input(self):
        import copy
        before=copy.deepcopy(self.nodes)
        d.suggest_links(self.nodes,{},'game')
        self.assertEqual(self.nodes,before)
    def test_invalid_source(self):
        with self.assertRaises(KeyError):
            d.suggest_links(self.nodes,{},'nonexistent')
    def test_limit_bounded(self):
        self.assertLessEqual(len(d.suggest_links(self.nodes,{},'game',10000)),30)

if __name__=='__main__': unittest.main()


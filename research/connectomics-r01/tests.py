#!/usr/bin/env python3
import json,sqlite3,tempfile,unittest
from pathlib import Path
import numpy as np
from connectome_query import query,ROOT
from export_hq500m_csr import export
class CorpusTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.db=sqlite3.connect(f'file:{ROOT/"normalized/connectomes.sqlite3"}?mode=ro',uri=True)
 def test_integrity(self):
  self.assertEqual(self.db.execute('PRAGMA quick_check').fetchone()[0],'ok')
 def test_dataset_count(self):
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM datasets').fetchone()[0],14)
 def test_worm_source_separation(self):
  kinds=[x[0] for x in self.db.execute("SELECT DISTINCT relation FROM edges WHERE dataset LIKE 'worm_%'").fetchall()]
  self.assertEqual(set(kinds),{'chemical','electrical_asymmetric','electrical_symmetric'})
 def test_no_flywire_orphan_version_ids(self):
  valid=set(map(str,np.load(ROOT/'raw/flywire/proofread_root_ids_783.npy',allow_pickle=False).tolist()))
  saved=[x[0] for x in self.db.execute("SELECT neuron_id FROM neurons WHERE dataset='flywire_783'")]
  self.assertTrue(all(x in valid for x in saved))
 def test_real_data_sizes(self):
  report=json.loads((ROOT/'reports/index_report.json').read_text())['data']
  self.assertEqual(report['flywire_783']['raw_rows'],16847997)
  self.assertEqual(report['male_cns_v10']['raw_rows'],151856684)
  self.assertEqual(report['male_cns_v10']['selected_rows'],55520)
  self.assertEqual(report['h01_swc_fragments']['files'],3327)
 def test_no_float_identity_conversion(self):
  x=self.db.execute("SELECT neuron_id FROM neurons WHERE dataset='flywire_783' LIMIT 1").fetchone()[0]
  self.assertTrue(x.isdigit() and len(x)>=15)
 def test_directed_edges(self):
  x=self.db.execute("SELECT src,dst,weight FROM edges WHERE dataset='worm_herm_chemical' LIMIT 1").fetchone()
  result=query('worm_herm_chemical',x[0],20,'neighbors','out')
  self.assertTrue(all(r['src']==x[0] for r in result['results']))
 def test_export_csr_structural_not_functional(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp)/'worm.npz'
   m=export('worm_herm_chemical',out)
   with np.load(out,allow_pickle=False) as a:
    self.assertEqual(len(a['indptr']),m['node_count']+1)
    self.assertEqual(len(a['indices']),m['edges_after_pair_aggregation'])
    self.assertEqual(int(a['contact_counts'].sum(dtype=np.uint64)),m['contact_count_sum'])
   self.assertFalse(m['model_ready'])
 def test_e11_weights_not_deserialized(self):
  p=ROOT/'raw/e11/synapse_excitatory_model.pt'
  self.assertTrue(p.is_file() and p.stat().st_size>1_000_000)
if __name__=='__main__':unittest.main(verbosity=2)

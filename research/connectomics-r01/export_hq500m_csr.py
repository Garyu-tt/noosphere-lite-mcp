#!/usr/bin/env python3
"""Export indexed structural adjacency to CSR. Contact counts ≠ functional synaptic strengths."""
import argparse,hashlib,json,sqlite3,datetime
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
def export(dataset,out):
 db=sqlite3.connect(f'file:{ROOT/"normalized/connectomes.sqlite3"}?mode=ro',uri=True)
 db.execute('PRAGMA query_only=ON')
 records=db.execute('SELECT src,dst,weight FROM edges WHERE dataset=? ORDER BY src,dst,weight DESC',(dataset,)).fetchall()
 if not records:raise ValueError('Unknown or empty dataset: '+dataset)
 ids=sorted(set(x for a,b,_ in records for x in (a,b)))
 idmap={key:i for i,key in enumerate(ids)}
 adjacency={}
 for a,b,w in records:
  k=(idmap[a],idmap[b])
  adjacency[k]=adjacency.get(k,0)+w
 edges=sorted(adjacency.items())
 degree=np.bincount(np.fromiter((u for (u,v),w in edges),dtype=np.int64),minlength=len(ids))
 indptr=np.empty(len(ids)+1,dtype=np.int64)
 indptr[0]=0;np.cumsum(degree,out=indptr[1:])
 indices=np.asarray([v for (u,v),w in edges],dtype=np.int64)
 contact_counts=np.asarray([w for k,w in edges],dtype=np.uint32)
 out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
 np.savez_compressed(out, ids=np.array(ids,dtype='U32'), indptr=indptr, indices=indices, contact_counts=contact_counts)
 h=hashlib.sha256(out.read_bytes()).hexdigest()
 manifest={'dataset':dataset,'source':'Noosphere connectomics corpus r01 / normalized/connectomes.sqlite3',
  'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'node_count':len(ids),'edges_after_pair_aggregation':len(edges),
  'contact_count_sum':int(contact_counts.sum(dtype=np.uint64)),
  'sha256':h,'model_ready':False,'causal_dynamics_known':False,'synapse_weights_known':False,
  'contact_counts_not_functional_weights':True,'unit':'number of anatomical contacts',
  'sex_species_stage_must_not_be_mixed':True,
  'index_may_be_filtered':'see reports/index_report.json'}
 out.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 db.close();return manifest

if __name__=='__main__':
 p=argparse.ArgumentParser()
 p.add_argument('--dataset',default='worm_herm_chemical')
 p.add_argument('--output')
 a=p.parse_args()
 dst=a.output or str(ROOT/'normalized/exports'/f'{a.dataset}.npz')
 print(json.dumps(export(a.dataset,dst),indent=2))

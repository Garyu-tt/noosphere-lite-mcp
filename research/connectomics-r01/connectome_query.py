#!/usr/bin/env python3
"""Read-only connectome navigator: source-aware answers, no claims of physiology."""
import argparse,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DB=ROOT/'normalized/connectomes.sqlite3'
def query(dataset,neuron=None,limit=10,mode='neighbors',direction='out'):
 assert 0<limit<=200,'Limit must be 1..200'
 if not DB.exists():raise SystemExit('Index missing. Run build_index.py')
 db=sqlite3.connect(f'file:{DB}?mode=ro',uri=True)
 db.row_factory=sqlite3.Row
 db.execute('PRAGMA query_only=ON')
 if mode=='list':
  rows=db.execute('SELECT dataset,description,data_version,type,source_license,caveat FROM datasets ORDER BY dataset').fetchall()
 elif mode=='stats':
  rows=db.execute('SELECT dataset,COUNT(*) AS indexed_rows,SUM(weight) AS indexed_contact_weight FROM edges GROUP BY dataset ORDER BY dataset').fetchall()
 elif mode=='hub':
  rows=db.execute('SELECT src,COUNT(*) AS connections,SUM(weight) AS indexed_contact_weight FROM edges WHERE dataset=? GROUP BY src ORDER BY indexed_contact_weight DESC LIMIT ?', (dataset,limit)).fetchall()
 elif mode=='morphology':
  rows=db.execute('SELECT * FROM morphologies WHERE dataset=? ORDER BY nodes DESC LIMIT ?',(dataset,limit)).fetchall()
 elif mode=='cell':
  if neuron is None:raise SystemExit('Provide --neuron for cell')
  rows=db.execute('SELECT * FROM neurons WHERE dataset=? AND neuron_id=? LIMIT ?', (dataset,neuron,limit)).fetchall()
 elif mode=='neighbors':
  if neuron is None:raise SystemExit('Provide --neuron for neighbors')
  cond='src=?' if direction=='out' else 'dst=?'
  rows=db.execute(f'SELECT src,dst,weight,relation,region,provenance,attrs_json FROM edges WHERE dataset=? AND {cond} ORDER BY weight DESC LIMIT ?', (dataset,neuron,limit)).fetchall()
 else:raise SystemExit(f'Unknown mode: {mode}')
 out={'dataset':dataset,'query_type':mode,'completeness':'indexed_subset_except_worm','physiology_inference':False,'results':[dict(r) for r in rows]}
 if dataset:
  m=db.execute('SELECT * FROM datasets WHERE dataset=?',(dataset,)).fetchone()
  out['source']=dict(m) if m else None
 db.close()
 return out

def main():
 p=argparse.ArgumentParser(description='Query the Noosphere connectomics atlas in read-only mode')
 p.add_argument('action',choices=['list','stats','neighbors','hub','morphology','cell'])
 p.add_argument('--dataset',default='worm_herm_chemical')
 p.add_argument('--neuron',help='Exact neuron/body ID, no float conversion')
 p.add_argument('--limit',type=int,default=10)
 p.add_argument('--direction',choices=['out','in'],default='out')
 a=p.parse_args()
 print(json.dumps(query(a.dataset,a.neuron,a.limit,a.action,a.direction),ensure_ascii=False,indent=2))

if __name__=='__main__':main()

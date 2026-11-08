#!/usr/bin/env python3
"""Structural-only analysis: never infer behavior or physiological synaptic signs."""
import collections,datetime,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DB=ROOT/'normalized/connectomes.sqlite3'
OUT=ROOT/'reports/topology_report.json'
def topological_analysis(db,dataset):
 rows=db.execute('SELECT src,dst,weight FROM edges WHERE dataset=?',(dataset,))
 src_weight=collections.Counter();dst_weight=collections.Counter()
 pair={};vertices=set()
 for a,b,w in rows:
  vertices.update((a,b))
  src_weight[a]+=w;dst_weight[b]+=w
  pair[(a,b)]=pair.get((a,b),0)+w
 reciprocal=sum(1 for (a,b) in pair if a!=b and (b,a) in pair)//2
 return {'dataset':dataset,'scope':'full_corrected_matrix' if dataset.startswith('worm_') else 'STRONG_EDGE_SUBSET_ONLY',
  'observed_nodes_in_index':len(vertices),'directed_pair_count':len(pair),
  'reciprocal_pair_count':reciprocal,'top_outgoing_contact_counts':src_weight.most_common(12),
  'top_incoming_contact_counts':dst_weight.most_common(12),
  'top_reciprocal_contact_pairs':[
   {'a':a,'b':b,'a_to_b':w,'b_to_a':pair[b,a]}
   for _,a,b,w in sorted(((min(w,pair[b,a]),a,b,w) for (a,b),w in pair.items() if a<b and (b,a) in pair),reverse=True)[:10]],
  'not_functional_synaptic_strength':True}
def main():
 db=sqlite3.connect(f'file:{DB}?mode=ro',uri=True);db.execute('PRAGMA query_only=ON')
 rep={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'metrics_are_anatomical_only':True,
  'warnings':['No neuronal firing or physiological weights implied','Subset filters prevent unbiased species-to-species network comparisons'],
  'datasets':[topological_analysis(db,d) for d in ['worm_herm_chemical','worm_male_chemical','flywire_783','male_cns_v10','banc_v888_v3','hemibrain_v12']]}
 q=db.execute("SELECT attrs_json,weight FROM edges WHERE dataset='banc_v888_v2_compartment'")
 c=collections.Counter()
 for data,w in q:
  v=json.loads(data)
  c[(v.get('pre_compartment'),v.get('post_compartment'))]+=w
 rep['banc_v888_v2_compartments']={'only_indexed_strong_edges':True,'top_compartment_contact_sums':[
  {'pre':a,'post':b,'indexed_contacts':n} for ((a,b),n) in c.most_common(20)]}
 q=db.execute("SELECT region,SUM(weight) FROM edges WHERE dataset='flywire_783' GROUP BY region ORDER BY SUM(weight) DESC LIMIT 30")
 rep['flywire_783_neuropil_strong_edges']={'minimum_weight':40,'neuropil_indexed_contact_sum_top30':[{'region':a,'contacts':b} for a,b in q]}
 n=db.execute('SELECT COUNT(*),SUM(nodes),MIN(nodes),MAX(nodes) FROM morphologies').fetchone()
 rep['h01_swc_fragments']={'fragment_files':n[0],'nodes_total':n[1],'nodes_min':n[2],'nodes_max':n[3],'not_unique_neuron_count':True,'units_not_assumed':True}
 db.close()
 OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n')
 for x in rep['datasets']:
  print(x['dataset'],'nodes',x['observed_nodes_in_index'],'pairs',x['directed_pair_count'],'reciprocal',x['reciprocal_pair_count'],'top_src',x['top_outgoing_contact_counts'][:3])
 print('h01',rep['h01_swc_fragments'])
 print('report',OUT)
if __name__=='__main__':main()

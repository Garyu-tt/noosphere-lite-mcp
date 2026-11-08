#!/usr/bin/env python3
"""Non-destructive, provenance-preserving connectome curation. Never runs downloaded weights."""
import argparse,csv,datetime,gzip,hashlib,heapq,io,json,os,sqlite3,tarfile,zipfile
from collections import Counter
from pathlib import Path
import numpy as np
import pyarrow.compute as pc
import pyarrow.feather as feather
import openpyxl
ROOT=Path(__file__).resolve().parent
RAW=ROOT/'raw'
DB=ROOT/'normalized/connectomes.sqlite3'
TODAY=datetime.datetime.now(datetime.timezone.utc).isoformat()

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
 return h.hexdigest()

def add_edges(db,ds,rows):
 db.executemany('INSERT INTO edges(dataset,src,dst,weight,relation,region,provenance,attrs_json) VALUES(?,?,?,?,?,?,?,?)',
  ((ds,str(src),str(dst),int(weight),relation,region,source,
    json.dumps(attrs,ensure_ascii=False,separators=(',',':')) if attrs else '{}')
   for src,dst,weight,relation,region,source,attrs in rows))

def setup(db):
 db.executescript('''
 PRAGMA journal_mode=WAL;
 PRAGMA synchronous=NORMAL;
 CREATE TABLE edges (dataset TEXT NOT NULL,src TEXT NOT NULL,dst TEXT NOT NULL,weight INTEGER NOT NULL,relation TEXT NOT NULL,region TEXT,provenance TEXT NOT NULL,attrs_json TEXT NOT NULL);
 CREATE TABLE neurons(dataset TEXT NOT NULL, neuron_id TEXT NOT NULL, cell_type TEXT, cell_class TEXT, neurotransmitter TEXT, attributes TEXT);
 CREATE TABLE morphologies(dataset TEXT, fragment_id TEXT, nodes INTEGER, minx REAL,miny REAL,minz REAL,maxx REAL,maxy REAL,maxz REAL,original_swc TEXT);
 CREATE TABLE crosswalk(source_dataset TEXT,target_dataset TEXT,source_id TEXT,target_id TEXT,score REAL,method TEXT,validation TEXT,provenance TEXT);
 CREATE TABLE neuron_metrics(dataset TEXT,neuron_id TEXT,n_input INTEGER,n_output INTEGER,avg_input_size REAL,avg_output_size REAL,provenance TEXT);
 CREATE TABLE datasets(dataset TEXT PRIMARY KEY,description TEXT NOT NULL,raw_source TEXT, data_version TEXT, type TEXT, source_license TEXT, caveat TEXT, recorded_at TEXT);
 ''')

def celegans(db,report):
 source='raw/celegans/Cook2019_corrected2020.xlsx'
 wb=openpyxl.load_workbook(RAW/'celegans/Cook2019_corrected2020.xlsx',read_only=True,data_only=True)
 for sheet in wb.worksheets[1:]:
  names=list(next(sheet.iter_rows(min_row=3,max_row=3,values_only=True)))
  kind='chemical' if 'chemical' in sheet.title else ('electrical_symmetric' if 'symmetric' in sheet.title and 'asymmetric' not in sheet.title else 'electrical_asymmetric')
  sex='herm' if sheet.title.startswith('hermaphrodite') else 'male'
  ds='worm_'+sex+'_'+kind
  def edges():
   for row in sheet.iter_rows(min_row=4,values_only=True):
    src=row[2]
    if not isinstance(src,str) or not src.strip():continue
    for ci,val in enumerate(row):
     if ci<3 or ci>=len(names) or not isinstance(names[ci],str) or not names[ci].strip():continue
     try:w=int(float(val))
     except (TypeError,ValueError):continue
     if w<=0:continue
     yield src,names[ci],w,kind,None,f'{source}#sheet={sheet.title}',{}
  # Electrical symmetric and asymmetric represent alternate views. Do NOT sum them.
  add_edges(db,ds,edges())
  k=db.execute('SELECT COUNT(*),SUM(weight) FROM edges WHERE dataset=?',(ds,)).fetchone()
  report[ds]={'rows':k[0],'weight_sum':k[1],'exact':True,'note':'The two electrical matrices are alternative views, not additive.'}
 wb.close()

def pick_arrow(db,path,ds,minweight,columns,relation,annotate_nt=False):
 t=feather.read_table(RAW/path,memory_map=True)
 col='syn_count' if 'syn_count' in t.column_names else 'weight'
 mask=pc.greater_equal(t[col],minweight)
 sel=t.filter(mask)
 total_raw=t.num_rows
 print(ds,'raw_rows',total_raw,'selected_rows',sel.num_rows,flush=True)
 del t,mask
 cols={x:sel[x].to_pylist() for x in columns}
 def rows():
  for i in range(sel.num_rows):
   src=cols[columns[0]][i];dst=cols[columns[1]][i];weight=cols[col][i]
   region=cols['neuropil'][i] if 'neuropil' in cols else None
   attrs={}
   if annotate_nt:
    vals=[(nt,float(cols[key][i])) for nt,key in [('GABA','gaba_avg'),('ACh','ach_avg'),('Glu','glut_avg'),('Oct','oct_avg'),('5-HT','ser_avg'),('DA','da_avg')] if cols[key][i] is not None]
    if vals:
     nt,score=max(vals,key=lambda x:x[1]);attrs={'nt_prediction':nt,'nt_score':round(score,4),'predicted_not_measured':True}
   yield src,dst,weight,relation,region,'raw/'+path,attrs
 add_edges(db,ds,rows())
 return {'raw_rows':total_raw,'minimum_weight_in_index':minweight,'selected_rows':sel.num_rows,'exact_full_data':True,'indexed_subset':True}

def hemibrain(db,report):
 p=RAW/'hemibrain/exported-traced-adjacencies-v1.2.tar.gz'
 with tarfile.open(p) as z:
  member=next(m for m in z if m.name.endswith('/traced-total-connections.csv'))
  rows=csv.DictReader(io.TextIOWrapper(z.extractfile(member),encoding='utf-8'))
  heap=[];total=0;weight_sum=0
  for row in rows:
   w=int(row['weight']);total+=1;weight_sum+=w
   e=(w,row['bodyId_pre'],row['bodyId_post'])
   if len(heap)<60000:heapq.heappush(heap,e)
   elif w>heap[0][0]:heapq.heapreplace(heap,e)
  add_edges(db,'hemibrain_v12',((a,b,w,'chemical',None,'raw/hemibrain/exported-traced-adjacencies-v1.2.tar.gz#traced-total-connections.csv',{}) for w,a,b in heap))
  neurons=next(m for m in z if m.name.endswith('/traced-neurons.csv'))
  neurons=csv.DictReader(io.TextIOWrapper(z.extractfile(neurons),encoding='utf-8'))
  db.executemany('INSERT INTO neurons VALUES(?,?,?,?,?,?)',(('hemibrain_v12',r['bodyId'],r['type'],None,None,json.dumps({'instance':r['instance']})) for r in neurons))
 report['hemibrain_v12']={'raw_rows':total,'raw_weight_sum':weight_sum,'selected_rows':len(heap),'indexed_subset':True,'exact_full_data':True}

def larval(db,report):
 path=RAW/'larval_fly/Winding2023_supplemental_S1.zip'
 with zipfile.ZipFile(path) as z:
  for typ in ['aa','ad','da','dd']:
   n=f'Supplementary-Data-S1/{typ}_connectivity_matrix.csv'
   ds='larval_fly_'+typ
   f=csv.reader(io.TextIOWrapper(z.open(n),encoding='utf-8'))
   names=next(f); total=0;eligible=0;sumw=0;stored=[]
   for line in f:
    if not line:continue
    src=line[0]
    for dst,val in zip(names[1:],line[1:]):
     try:w=int(float(val))
     except (TypeError,ValueError):continue
     if w>0:total+=1;sumw+=w
     if w>=20:eligible+=1;stored.append((src,dst,w,'compartment_'+typ,None,'raw/larval_fly/Winding2023_supplemental_S1.zip#'+n,{}))
   add_edges(db,ds,stored)
   report[ds]={'raw_nonzero_connections':total,'raw_weight_sum':sumw,'minimum_weight_in_index':20,'selected_rows':len(stored),'indexed_subset':True,'exact_full_data':True}
   print(ds,'raw_nonzero',total,'selected',len(stored),flush=True)

def morphology(db,report):
 path=RAW/'h01/104_proofread_neurons_swc.zip'
 rows=[];nodes_total=0
 with zipfile.ZipFile(path) as z:
  for m in z.infolist():
   if not m.filename.endswith('.swc'):continue
   num=0;mins=[float('inf')]*3;maxs=[float('-inf')]*3
   with z.open(m) as stream:
    for line in stream:
     if line.startswith(b'#'):continue
     parts=line.split()
     if len(parts)<7:continue
     try: xyz=[float(parts[i]) for i in (2,3,4)]
     except ValueError:continue
     num+=1
     for k in range(3):mins[k]=min(mins[k],xyz[k]);maxs[k]=max(maxs[k],xyz[k])
   if not num:continue
   nodes_total+=num
   rows.append(('h01_swc_fragments',m.filename,num,*mins,*maxs,'raw/h01/104_proofread_neurons_swc.zip#'+m.filename))
 db.executemany('INSERT INTO morphologies VALUES(?,?,?,?,?,?,?,?,?,?)',rows)
 report['h01_swc_fragments']={'files':len(rows),'skeleton_nodes':nodes_total,'not_full_human_connectome':True,
   'note':'SWC filenames are fragments; not necessarily distinct neuron identities or synapses. Units not inferred.'}

def banc(db,report):
 base='banc/'
 for version,filename,cutoff in [('banc_v888_v3','banc_888_edgelist_simple_v3.feather',40),('banc_v888_v2_compartment','banc_888_edgelist_split_v2.feather',40)]:
  t=feather.read_table(RAW/base/filename,memory_map=True)
  total=t.num_rows;weighted=pc.sum(t['count']).as_py()
  sel=t.filter(pc.greater_equal(t['count'],cutoff))
  columns=['pre','post','count']+(['pre_label','post_label','connection','pre_conf_nt','pre_conf_nt_p','post_conf_nt','post_conf_nt_p'] if version.endswith('compartment') else [])
  a={name:sel[name].to_pylist() for name in columns}
  def records():
   for i in range(sel.num_rows):
    attrs={}
    if version.endswith('compartment'):
     attrs={'pre_compartment':a['pre_label'][i],'post_compartment':a['post_label'][i],
      'nt_predict_pre':a['pre_conf_nt'][i],'nt_confidence_pre':a['pre_conf_nt_p'][i],
      'nt_predict_post':a['post_conf_nt'][i],'nt_confidence_post':a['post_conf_nt_p'][i],
      'neurotransmitters_not_measured':True}
    yield (a['pre'][i],a['post'][i],a['count'][i],
      'chemical_compartment' if version.endswith('compartment') else 'chemical', None,
      'raw/'+base+filename,attrs)
  add_edges(db,version,records())
  report[version]={'raw_rows':total,'raw_contact_sum':weighted,'indexed_rows':sel.num_rows,'threshold':cutoff,'indexed_subset':True,
   'warning':'BANC v2/v3 are different synapse versions: do NOT combine or sum them.'}
  del sel,t,a
  db.commit()
  print(version,'raw_rows',total,'indexed',report[version]['indexed_rows'],flush=True)
 meta=feather.read_table(RAW/base/'banc_888_meta.feather',memory_map=True)
 relevant=['banc_888_id','cell_type','cell_class','super_class','proofread','root_888']
 fields={x:meta[x].to_pylist() for x in relevant}
 def rows():
  for i,id in enumerate(fields['banc_888_id']):
   if id is None:continue
   attrs={'super_class':fields['super_class'][i],'proofread':fields['proofread'][i],'root_888':fields['root_888'][i]}
   yield 'banc_v888_v3',str(id),fields['cell_type'][i],fields['cell_class'][i],None,json.dumps(attrs,ensure_ascii=False,separators=(',',':'))
 db.executemany('INSERT INTO neurons VALUES(?,?,?,?,?,?)',rows())
 report['banc_meta']={'rows':meta.num_rows,'id_key':'banc_888_id'}
 # Morphological similarity is a candidate cross-atlas link, NOT neuron identity.
 nt=feather.read_table(RAW/base/'banc_fafb_783_nblast.feather',memory_map=True)
 candidates=nt.filter(pc.greater_equal(nt['score'],0.8))
 arrays={x:candidates[x].to_pylist() for x in ('query_root_id','match_id','score','validation')}
 db.executemany('INSERT INTO crosswalk VALUES(?,?,?,?,?,?,?,?)',
  (('banc_v888_v3','flywire_783',str(arrays['query_root_id'][i]),str(arrays['match_id'][i]),
    float(arrays['score'][i]),'NBLAST_morphology_candidate','validated_flag' if arrays['validation'][i] else 'unvalidated',
    'raw/'+base+'banc_fafb_783_nblast.feather') for i in range(candidates.num_rows)))
 report['banc_fafb_nblast']={'raw_rows':nt.num_rows,'indexed_score_min':0.8,'candidate_links':candidates.num_rows,
  'warning':'NBLAST morphological similarity, not biological identity'}
 db.commit()

def microns(db,report):
 # Static, historic MICrONS release v661. The current v1926 API is NOT represented by these files.
 base=RAW/'microns_v661'
 total=0;stored=0
 with gzip.open(base/'synapses_pni_2_in_out_degree.csv.gz','rt',newline='') as f:
  for row in csv.reader(f):
   try:
    root,ni,avg_i,no,avg_o=row
    ni=int(ni);no=int(no);total+=1
    if ni+no<500:continue
    db.execute('INSERT INTO neuron_metrics VALUES(?,?,?,?,?,?,?)',
     ('microns_v661',root,ni,no,float(avg_i),float(avg_o),
      'raw/microns_v661/synapses_pni_2_in_out_degree.csv.gz'))
    stored+=1
   except (ValueError,TypeError):
    continue
 nuclei=0;aligned=0
 with gzip.open(base/'nucleus_detection_v0_merged.csv.gz','rt',newline='') as f:
  for row in csv.reader(f):
   nuclei+=1
   try:
    nucl,volume,sv,root,x,y,z=row
    if not root or root=='0':continue
   except ValueError:continue
   db.execute('INSERT INTO neurons VALUES(?,?,?,?,?,?)',
    ('microns_v661',root,None,None,None,
      json.dumps({'nucleus_id':nucl,'volume':volume,'xyz_source_units_unconfirmed':[x,y,z]},
       ensure_ascii=False,separators=(',',':'))))
   aligned+=1
 report['microns_v661']={'full_degree_rows':total,'strong_degree_rows_indexed':stored,'degree_threshold_n_input_plus_n_output':500,
  'nucleus_rows_raw':nuclei,'nuclei_with_nonzero_root_id':aligned,'edges_downloaded':False,
  'note':'Archived MICrONS static v661 (NOT v1926 portal); graph connectivity edges and functional physiology NOT downloaded.'}
 db.commit()
 print('MICrONS v661 degree rows',total,'indexed',stored,'mapped nuclei',aligned,flush=True)

def fly_annotations(db,report):
 p=RAW/'flywire/neuron_annotations_783.tsv'
 valid_ids=set(map(str,np.load(RAW/'flywire/proofread_root_ids_783.npy',allow_pickle=False).tolist()))
 count=0;rejected=0
 with open(p,encoding='utf-8') as f:
  r=csv.DictReader(f,delimiter='\t')
  def rows():
   nonlocal count,rejected
   for x in r:
    if not x.get('root_id'):continue
    if x['root_id'] not in valid_ids:
     rejected+=1
     continue
    count+=1
    yield ('flywire_783',x['root_id'],x.get('cell_type'),x.get('cell_class'),x.get('top_nt'),
      json.dumps({'super_class':x.get('super_class'),'cell_sub_class':x.get('cell_sub_class'),'status':x.get('status'),'top_nt_conf':x.get('top_nt_conf')},ensure_ascii=False,separators=(',',':')))
  db.executemany('INSERT INTO neurons VALUES(?,?,?,?,?,?)',rows())
 report['flywire_annotations']={'rows':count,'rejected_cross_version_ids':rejected,'warning':'Strict intersection with proofread_root_ids_783.npy; never auto-merge cross-version IDs.'}

def male_annotations(db,report):
 p=RAW/'malecns/body-annotations-male-cns-v1.0.feather'
 t=feather.read_table(p,memory_map=True)
 col={c:t[c].to_pylist() for c in ['bodyId','type','class','superclass','status']}
 rows=[]
 for i,body in enumerate(col['bodyId']):
  rows.append(('male_cns_v10',str(body),col['type'][i],col['class'][i],None,
   json.dumps({'superclass':col['superclass'][i],'status':col['status'][i]},ensure_ascii=False,separators=(',',':'))))
 db.executemany('INSERT INTO neurons VALUES(?,?,?,?,?,?)',rows)
 report['male_cns_annotations']={'rows':len(rows),'notes':'NT predictions stored in raw feather; not assumed ground truth.'}

def main():
 DB.parent.mkdir(exist_ok=True,parents=True)
 temp=DB.with_name('connectomes.build.sqlite3')
 for name in [temp,temp.with_name(temp.name+'-wal'),temp.with_name(temp.name+'-shm')]:
  if name.exists():name.unlink()
 db=sqlite3.connect(temp)
 setup(db);report={}
 celegans(db,report);db.commit()
 print('worm done',flush=True)
 flycols=['pre_pt_root_id','post_pt_root_id','syn_count','neuropil','gaba_avg','ach_avg','glut_avg','oct_avg','ser_avg','da_avg']
 report['flywire_783']=pick_arrow(db,'flywire/proofread_connections_783.feather','flywire_783',40,flycols,'chemical',True);db.commit()
 report['male_cns_v10']=pick_arrow(db,'malecns/connectome-weights-male-cns-v1.0.feather','male_cns_v10',100,['body_pre','body_post','weight'],'chemical');db.commit()
 hemibrain(db,report);db.commit()
 banc(db,report);db.commit()
 microns(db,report);db.commit()
 print('hemibrain done',flush=True)
 larval(db,report);db.commit()
 print('larval done',flush=True)
 morphology(db,report);db.commit()
 print('h01 done',flush=True)
 fly_annotations(db,report);male_annotations(db,report);db.commit()
 print('annotations done',flush=True)
 for id,description,raw,ver,kind,lic,caveat in [
  ('worm_herm_chemical','C. elegans adult hermaphrodite chemical synapses','raw/celegans/Cook2019_corrected2020.xlsx','Cook 2019 / corrected 2020','chemical','review','Full corrected matrix; includes non-neuronal endpoints'),
  ('worm_herm_electrical_asymmetric','C. elegans adult hermaphrodite asymmetric gap junctions','raw/celegans/Cook2019_corrected2020.xlsx','Cook 2019 / corrected 2020','electrical','review','Alternate asymmetric electrical view, not additive'),
  ('worm_herm_electrical_symmetric','C. elegans adult hermaphrodite symmetric gap junctions','raw/celegans/Cook2019_corrected2020.xlsx','Cook 2019 / corrected 2020','electrical','review','Alternate symmetric electrical view, not additive'),
  ('worm_male_chemical','C. elegans adult male chemical synapses','raw/celegans/Cook2019_corrected2020.xlsx','Cook 2019 / corrected 2020','chemical','review','Full corrected matrix; includes non-neuronal endpoints'),
  ('worm_male_electrical_asymmetric','C. elegans adult male asymmetric gap junctions','raw/celegans/Cook2019_corrected2020.xlsx','Cook 2019 / corrected 2020','electrical','review','Alternate asymmetric electrical view, not additive'),
  ('worm_male_electrical_symmetric','C. elegans adult male symmetric gap junctions','raw/celegans/Cook2019_corrected2020.xlsx','Cook 2019 / corrected 2020','electrical','review','Alternate symmetric electrical view, not additive'),
  ('flywire_783','Drosophila adult female whole brain','raw/flywire/proofread_connections_783.feather','FAFB v783','chemical','CC BY-NC 4.0 restrictive guidelines','Indexed strong subset only; neurotransmitters predicted'),
  ('male_cns_v10','Drosophila male entire CNS (brain+cord)','raw/malecns/connectome-weights-male-cns-v1.0.feather','MaleCNS v1.0','chemical','CC BY 4.0','Indexed strong subset only; source weighted edges'),
  ('hemibrain_v12','Drosophila hemibrain','raw/hemibrain/exported-traced-adjacencies-v1.2.tar.gz','hemibrain v1.2','chemical','CC BY 4.0','Partial brain; top 60,000 strong edges indexed'),
  ('larval_fly_aa','Drosophila larval axon-to-axon','raw/larval_fly/Winding2023_supplemental_S1.zip','Winding 2023','chemical','verify','Synaptic compartment label; threshold >=20'),
  ('larval_fly_ad','Drosophila larval axon-to-dendrite','raw/larval_fly/Winding2023_supplemental_S1.zip','Winding 2023','chemical','verify','Synaptic compartment label; threshold >=20'),
  ('larval_fly_da','Drosophila larval dendrite-to-axon','raw/larval_fly/Winding2023_supplemental_S1.zip','Winding 2023','chemical','verify','Synaptic compartment label; threshold >=20'),
  ('larval_fly_dd','Drosophila larval dendrite-to-dendrite','raw/larval_fly/Winding2023_supplemental_S1.zip','Winding 2023','chemical','verify','Synaptic compartment label; threshold >=20'),
  ('microns_v661','Mouse visual cortex nuclei and synapse-degree static summary','raw/microns_v661/synapses_pni_2_in_out_degree.csv.gz','MICrONS historic static materialization v661','degree_metadata','verify MICrONS original terms','Not full connectome: degree metadata only; do not mix with v1926 without version reconciliation'),
  ('banc_v888_v3','Adult female Drosophila full brain and nerve cord','raw/banc/banc_888_edgelist_simple_v3.feather','BANC 888/v3','chemical','verify source rights','v3; strongest contacts indexed; cross-atlas nblast links are not neuronal identity'),
  ('banc_v888_v2_compartment','Adult female Drosophila compartment-specific brain and cord','raw/banc/banc_888_edgelist_split_v2.feather','BANC 888/v2','chemical','verify source rights','v2 compartment-specific connections; do not merge with v3'),
  ('h01_swc_fragments','Human H01 cortical 1 mm3 skeleton subset','raw/h01/104_proofread_neurons_swc.zip','H01 2021/2024','morphology','verify','3327 SWC files are fragments, not all H01 16k neurons')]:
  db.execute('INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?)',(id,description,raw,ver,kind,lic,caveat,TODAY))
 db.commit()
 db.executescript('CREATE INDEX edge_source ON edges(dataset,src); CREATE INDEX edge_target ON edges(dataset,dst); CREATE INDEX edge_rank ON edges(dataset,weight DESC); CREATE INDEX neuron_lookup ON neurons(dataset,neuron_id); CREATE INDEX morph_lookup ON morphologies(dataset,fragment_id); CREATE INDEX crosswalk_lookup ON crosswalk(source_dataset,source_id); CREATE INDEX neuron_metric_lookup ON neuron_metrics(dataset,neuron_id);')
 db.commit()
 print('indexes done',flush=True)
 integrity=db.execute('PRAGMA quick_check').fetchone()[0]
 report['db_integrity']=integrity
 report['indexed_edges']=db.execute('SELECT COUNT(*) FROM edges').fetchone()[0]
 report['indexed_neurons']=db.execute('SELECT COUNT(*) FROM neurons').fetchone()[0]
 report['indexed_morphology_fragments']=db.execute('SELECT COUNT(*) FROM morphologies').fetchone()[0]
 report['nblast_candidate_links']=db.execute('SELECT COUNT(*) FROM crosswalk').fetchone()[0]
 report['indexed_neuron_degree_rows']=db.execute('SELECT COUNT(*) FROM neuron_metrics').fetchone()[0]
 db.close();os.replace(temp,DB)
 json_report={'generated_at':TODAY,'source_release_dates_not_inferred_from_download_time':True,'data':report}
 (ROOT/'reports/index_report.json').write_text(json.dumps(json_report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'indexed_edges':report['indexed_edges'],'indexed_neurons':report['indexed_neurons'],'morphologies':report['indexed_morphology_fragments'],'quick_check':integrity},indent=2),flush=True)

if __name__=='__main__':main()

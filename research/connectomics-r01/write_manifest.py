#!/usr/bin/env python3
import datetime,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
origins={
 'banc/banc_888_edgelist_simple_v3.feather':'https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/banc_888_edgelist_simple_v3.feather',
 'banc/banc_888_edgelist_split_v2.feather':'https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/banc_888_edgelist_split_v2.feather',
 'banc/banc_888_meta.feather':'https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/compiled_data/banc_888/banc_888_meta.feather',
 'banc/banc_fafb_783_nblast.feather':'https://storage.googleapis.com/lee-lab_brain-and-nerve-cord-fly-connectome/nblast/banc_fafb_783_nblast.feather',
 'flywire/proofread_connections_783.feather':'https://zenodo.org/records/10676866/files/proofread_connections_783.feather?download=1',
 'flywire/proofread_root_ids_783.npy':'https://zenodo.org/records/10676866/files/proofread_root_ids_783.npy?download=1',
 'flywire/per_neuron_neuropil_count_pre_783.feather':'https://zenodo.org/records/10676866/files/per_neuron_neuropil_count_pre_783.feather?download=1',
 'flywire/neuron_annotations_783.tsv':'https://raw.githubusercontent.com/flyconnectome/flywire_annotations/main/supplemental_files/Supplemental_file1_neuron_annotations.tsv',
 'malecns/connectome-weights-male-cns-v1.0.feather':'https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/connectome-weights-male-cns-v1.0-minconf-0.5.feather',
 'malecns/body-annotations-male-cns-v1.0.feather':'https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/body-annotations-male-cns-v1.0-minconf-0.5.feather',
 'malecns/body-neurotransmitters-male-cns-v1.0.feather':'https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/body-neurotransmitters-male-cns-v1.0.feather',
 'h01/104_proofread_neurons_swc.zip':'https://storage.googleapis.com/h01-release/data/20210601/proofread_104/skeletons/104_proofread_neurons_swc.zip',
 'celegans/Cook2019_corrected2020.xlsx':'https://wormwiring.org/si/SI%205%20Connectome%20adjacency%20matrices%2C%20corrected%20July%202020.xlsx',
 'celegans/Cook2019_synapse_lists.xlsx':'https://wormwiring.org/si/SI%203%20Synapse%20lists.xlsx',
 'larval_fly/Winding2023_supplemental_S1.zip':'https://raw.githubusercontent.com/brain-networks/larval-drosophila-connectome/main/Supplementary-Data-S1.zip',
 'hemibrain/exported-traced-adjacencies-v1.2.tar.gz':'https://storage.googleapis.com/hemibrain/v1.2/exported-traced-adjacencies-v1.2.tar.gz',
}
manifest={'recorded_at':now,'observed_at':now,'valid_from':None,'valid_to':None,'local_files':[],'upstream_commits':[]}
for p in sorted((ROOT/'raw').rglob('*')):
 if not p.is_file() or p.suffix in ('.partial','.part'):continue
 rel=p.relative_to(ROOT/'raw').as_posix()
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
 manifest['local_files'].append({'path':'raw/'+rel,'size_bytes':p.stat().st_size,'sha256':h.hexdigest(),'origin':origins.get(rel,'https://e11bio-prism.s3.amazonaws.com/ls/models/checkpoints/ (specific prefix recorded in README)')})
for p in sorted((ROOT/'sources').iterdir()):
 if not (p/'.git').is_dir():continue
 commit=subprocess.check_output(['git','-c',f'safe.directory={p}','-C',str(p),'rev-parse','HEAD'],text=True).strip()
 origin=subprocess.check_output(['git','-c',f'safe.directory={p}','-C',str(p),'remote','get-url','origin'],text=True).strip()
 manifest['upstream_commits'].append({'project':p.name,'commit':commit,'origin':origin})
(ROOT/'reports/source_manifest_full.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
# safe public excerpt excludes local paths and hashes of binary payloads
subset={'recorded_at':now,'source_commit_pins':manifest['upstream_commits'],'files':[{'name':x['path'],'bytes':x['size_bytes'],'origin':x['origin']} for x in manifest['local_files']]}
(ROOT/'SOURCE_CATALOG_PUBLIC.json').write_text(json.dumps(subset,ensure_ascii=False,indent=2)+'\n')
print('manifest',len(manifest['local_files']),'files',sum(f['size_bytes'] for f in manifest['local_files']),'bytes')

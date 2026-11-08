# Noosphere Connectomics Corpus R01 — provenance, rights, readiness
Recorded and inspected 2026-11-08 UTC. Dataset sample collection is not an exhaustive list of all connectomes.
This corpus combines **local raw files**, **an independently tested read-only index** and **remote references**.
The presence of a paper, resource, trained checkpoint or connectome does NOT mean that HQ500M simulates the source organism.

## Local datasets — practical use

| Key | Primary origin | Local data | Key scientific use | Limitations |
|---|---|---|---|---|
| `flywire_783` | https://zenodo.org/records/10676866, https://doi.org/10.1038/s41586-024-07558-y | 16,847,997 neuropil-resolved partner rows (54,492,922 synapses); threshold >=40 indexed | directed anatomical adjacency, neuropil, probabilistic NT predictions | adult **female** fly *brain*, neurotransmitter is predicted |
| `male_cns_v10` | https://male-cns.janelia.org/release/ , https://doi.org/10.1016/j.cell.2026.08.015 | 151,856,684 weighted partner rows, 311,833,243 contacts; threshold >=100 indexed | entire male fly **brain+cord**, sensory-to-motor routing, sex comparison | v1.0; annotation and transmitter predictions remain uncertain |
| `hemibrain_v12` | https://storage.googleapis.com/hemibrain/v1.2/exported-traced-adjacencies-v1.2.tar.gz | complete compact adjacency CSV archive; strongest 60k indexed | older traceable benchmark and cross-assembly comparison | **partial** adult fly brain; not a whole organism |
| `larval_fly_aa/ad/da/dd` | https://github.com/brain-networks/larval-drosophila-connectome ; Winding et al., Science 2023 | four compartment-specific matrices, strength >=20 indexed | axon/dendrite compartment-specific connectivity | larval stage and compartment semantics preserved; do not replace adult wiring |
| `worm_herm_*`, `worm_male_*` | https://wormwiring.org/pages/adjacency.html ; https://doi.org/10.1038/s41586-019-1352-7 | complete 2020-corrected 2019 *C. elegans* adjacency (chemical and two **alternative** electrical views) | reproducible test circuits, directed chemical vs electrical connections, movement-related circuits | includes muscles and non-neuronal cells; electrical symmetric and asymmetric matrices must NEVER be summed |
| `banc_v888_v3` / `banc_v888_v2_compartment` | https://doi.org/10.7910/DVN/7WTH1N , https://github.com/htem/BANC-project/blob/main/manuscript/print/banc_data_locations.md | **13,620,865** v3 rows (sum of `count` 42,309,621) and **14,332,296** v2 compartment rows (sum 34,310,230); indexed >=40 separately. **188,508** metadata rows, **8,254,585** NBLAST matching candidates available, top score>=0.8 indexed | adult **female** brain+nerve cord, compartment location and cross-connectome morphological similarity for FlyWire | separate v2/v3 synapse definitions; NBLAST scores do NOT establish cell identity; source reuse terms need verification |
| `h01_swc_fragments` | https://h01-release.storage.googleapis.com/landing.html ; https://sites.research.google/gr/neural-mapping/datasets/ | 3,327 skeleton SWC files (not distinct neurons) in 1 zip | shape, arbor branching, geometry, path length studies | **sample** of ~1 mm³ human cortex, NOT a complete human connectome |
| `e11_prism` | https://github.com/e11bio/e11-open-data and https://registry.opendata.aws/e11bio-prism/ | selected official segmentation checkpoint files and JSON configs | multiplexed optical barcodes, error correction, segmentation, candidate synapse prediction | no complete mouse connectivity graph included; checkpoints are untrusted binary weights: **do not torch.load without sandboxing** |

**Release vs recording dates:** Data release/version time comes from original authors. `recorded_at` means our ingestion/record creation, NOT when a neuron or synapse originated. Unknown `valid_from` and `valid_to` must remain null.

## Other major public connectomes / repositories — not mirrored

- **MICrONS v1926**, mouse primary/higher visual cortex, https://www.microns-explorer.org/cortical-mm3 and https://doi.org/10.1038/s41586-025-08790-w . Hundreds of millions of synapses and ~75k calcium-imaged neurons. Excellent link between function and anatomy; huge, remote queries preferable.
- **Fish1**, larval zebrafish brain, https://fish1-release.storage.googleapis.com/index.html ; dense vertebrate ultrastructure and molecular labels, but not a proven complete neuronal wiring model.
- **Fish Fire&Wire**, 2026 draft larval zebrafish complete wiring, https://sites.research.google/gr/neural-mapping/datasets/ . A draft was finished 2026; direct comprehensive wiring access and proofread status must be checked; we did **not** download it.
- **MANC**, male fly ventral nerve cord v1.2.1, and **MAOL**, male optic lobe: https://codex.flywire.ai/api/download ; useful subsystem controls but the same neurons can overlap with whole-CNS datasets.
- **FANC**, female adult nerve cord; https://www.flywire.ai/ ; do not merge with BANC without exact identity and registration.
- **OpenWorm C. elegans Connectome Toolbox**, https://openworm.org/ConnectomeToolbox/ ; stage-specific alternative worm wiring and circuit models. Useful as independent consistency check against Cook 2019.
- **Human Connectome Project MRI** is macroscale tractography, **not** a synapse-level map. Never mix MRI edges and synaptic edges into one adjacency without a distinct layer.

## Scientific safeguards
1. **Species, sex, developmental stage, brain region, specimen, atlas, data version** are part of every dataset's identity. No unregistered cross-individual cell ID merges.
2. An anatomical **synapse/contact count is NOT a measured physiological conductance or signed weight**. Exported CSR uses an integer field `contact_counts`, explicitly flagged `model_ready=false`.
3. Cell-class labels, neurotransmitter probabilities, proofread status, and ROI are **annotations**, not guaranteed mechanistic truths.
4. Brain regions and local geometry require coordinate frames, affine transformations and original units. Do not stitch unregistered H01 SWC fragments or PRISM pixels.
5. Incomplete, cropped and unproofread segments must remain distinguishable; only exact release-matched IDs may be joined.
6. Cite original labs/publications and comply with source-specific use terms. No automatic model checkpoint execution.
7. Do not download petabytes by default. Data lake has less free space than a full imaging corpus; prefer indexed subsets, lazy bulk access and verified checksums.

## Licensing & distribution
- **FlyWire:** its own public release guidelines specify **CC BY-NC 4.0**, while some Zenodo packages show CC BY 4.0. Treat as a **license conflict** for re-publication. Until clarified, apply the stricter non-commercial policy and do **not** mirror raw files to our GitHub.
- **MaleCNS:** the Janelia release page states **CC BY**; preserve creators' attribution.
- **E11:** the project README states **CC BY-SA 4.0** for data; AWS registry links to their specific terms. Re-check both before redistribution or producing derivative checkpoints.
- **Hemibrain:** commonly released CC BY 4.0; cite FlyEM/Janelia.
- **BANC:** source files were downloaded from the project's official publicly accessible Google Cloud bucket. Check the source-specific licence terms before redistributing.
- **C. elegans, H01, larval supplemental:** research datasets have their own terms and provenance; not re-published in our software repository without explicit licensing review.
- The **Noosphere-authored scripts** may be distributed independently as our code. Public repository should contain only code, schemas and a source catalogue, **no raw brains / checkpoints**.

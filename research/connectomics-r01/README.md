# Noosphere Connectomics Corpus R01 (2026-11-08)
Provenance-first collection of real connectome datasets for scientific queries, structured comparison, and **non-executable** structural integration experiments with HQ500M / BitWeave. No official data is uploaded to GitHub.

**Directories:** `raw/` are untouched source archives and feather datasets; `sources/` are upstream git clones at fixed commits; `normalized/connectomes.sqlite3` is a reproducible read-only query index with **filtered strong-edge subsets** for large datasets; `normalized/exports/` are experimental small CSR adjacency maps; `reports/` contains tests and source-hash evidence.

**Run:**
```bash
cd ~/projects/noosphere-connectomics-corpus-r01
.venv/bin/python connectome_query.py list
.venv/bin/python connectome_query.py hub --dataset flywire_783 --limit 20
.venv/bin/python connectome_query.py morphology --dataset h01_swc_fragments --limit 5
.venv/bin/python connectome_query.py crosswalk --dataset banc_v888_v3 --limit 10
.venv/bin/python export_hq500m_csr.py --dataset worm_herm_chemical
.venv/bin/python tests.py
```
Rebuild requires the source files documented in SOURCES.md and Python `numpy`, `pyarrow`, `openpyxl`. Query needs only sqlite3, build needs the third-party dependencies. The state of HQ500M itself is **unchanged**; exported adjacency is structural and cannot by itself reproduce behavior.

**Temporal/provenance conventions:** `recorded_at` reflects local recording. `observed_at` captures inspection. `valid_from` and `valid_to` left null without evidence; authorship and release year are distinct fields.

See SOURCES.md for license conflicts, citations, scope, access and most important limitations.

**BANC v888:** the local index stores strong connections separately for v3 and compartment-resolved v2 (never sum the synapse counts across versions), plus 1,999 NBLAST v888↔FAFB v783 *morphological similarity candidates* (not neuron identity). Full raw BANC v3/v2 exports, annotation table and NBLAST scoring table remain in `raw/banc`.

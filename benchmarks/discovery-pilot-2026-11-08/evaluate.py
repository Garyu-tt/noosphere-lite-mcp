#!/usr/bin/env python3
"""Evaluate a human-readable pilot-label JSON. Stdlib only; no private DB required.

IMPORTANT: This measures manual usefulness *labels* on an already returned
candidate set. It does NOT estimate general retrieval recall and does not
establish real-world skill transfer or verified scientific inference.
"""
from collections import Counter
from pathlib import Path
import argparse
import json

LABELS={"useful","plausible","noise"}

def evaluate(data):
    sample=data["sample"]
    assert len(sample)==24, "frozen 24-item pilot sample required"
    assert len({s["id"] for s in sample})==len(sample), "duplicate candidate IDs"
    assert all(s["label"] in LABELS for s in sample), "invalid manual label"
    strata=data["strata"]
    by={}
    for stratum in strata:
        bucket=stratum["bucket"]
        group=[x for x in sample if x["bucket"]==bucket]
        assert len(group)==stratum["sampled"], "stratum mismatch"
        counts=Counter(x["label"] for x in group)
        by[bucket]={"population":stratum["population"],"sampled":len(group),
                    "useful":counts["useful"],"plausible":counts["plausible"],
                    "noise":counts["noise"]}
    assert sum(x["population"] for x in strata)==data["candidate_population"]
    counts=Counter(s["label"] for s in sample)
    n=len(sample)
    weighted_useful=sum(
        by[x["bucket"]]["population"] * by[x["bucket"]]["useful"]/x["sampled"]
        for x in strata
    )/data["candidate_population"]
    coverage=data["known_proposals"]
    assert len({x["id"] for x in coverage})==len(coverage)
    return {
        "reviewer":data["reviewer"],
        "candidate_population":data["candidate_population"],
        "sample_n":n,
        "sample_counts":{label:counts[label] for label in sorted(LABELS)},
        "sample_useful_fraction":round(counts["useful"]/n,4),
        "sample_nonnoise_fraction":round((counts["useful"]+counts["plausible"])/n,4),
        "stratum_weighted_useful_fraction":round(weighted_useful,4),
        "strata":by,
        "known_documented_proposals":len(coverage),
        "known_proposals_linked_before":sum(x["linked_before"] for x in coverage),
        "known_proposals_linked_after":sum(x["linked_after"] for x in coverage),
        "not_global_precision_or_recall":True,
        "no_independent_human_review":True
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("input",nargs="?",
        default=str(Path(__file__).with_name("pilot.json")))
    args=p.parse_args()
    data=json.loads(Path(args.input).read_text(encoding="utf-8"))
    print(json.dumps(evaluate(data),indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()

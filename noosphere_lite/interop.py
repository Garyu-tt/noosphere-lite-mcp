"""Opt-in, read-only graph adapters. Plaintext export is never automatic."""
import csv
import hashlib
import json
from pathlib import Path

def networkx_report(nodes, links, max_nodes=5000):
    """Bounded graph analytics, optional dependency."""
    if len(nodes) > max_nodes:
        raise ValueError("node budget exceeded")
    try:
        import networkx as nx
    except ImportError as exc:
        raise RuntimeError("Install networkx for graph analysis") from exc
    g = nx.DiGraph()
    g.add_nodes_from(k for k, n in nodes.items() if not n.get("archived"))
    for src, dst, rel in links:
        if src in g and dst in g:
            g.add_edge(src, dst, relation=rel)
    components = list(nx.weakly_connected_components(g))
    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
            "weak_components": len(components),
            "largest_component": max(map(len, components), default=0)}

def export_ladybug_csv(nodes, links, destination):
    """Create CSV staging files. Does NOT install/connect/migrate LadybugDB."""
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "nodes.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "kind", "status", "recorded_at", "valid_from", "valid_to"])
        for k, n in sorted(nodes.items()):
            if not n.get("archived"):
                w.writerow([k, n.get("title"), n.get("kind"), n.get("status"),
                            n.get("recorded_at") or n.get("created"),
                            n.get("valid_from"), n.get("valid_to")])
    with (dest / "edges.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "target", "relation", "recorded_at"])
        for (s, t, r), stamp in sorted(links.items()):
            if s in nodes and t in nodes and not nodes[s].get("archived") and not nodes[t].get("archived"):
                w.writerow([s, t, r, stamp])
    return {"directory": str(dest), "imported_into_ladybug": False, "plaintext_export": True}

def export_okf(nodes, links, destination):
    """OKF v0.2 Markdown/YAML plus typed-edge extension for fidelity."""
    dest = Path(destination)
    concepts = dest / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    index = ['---', 'okf_version: "0.2"', '---', '# Noosphere Lite export', '']
    exported = set()
    for key, n in sorted(nodes.items()):
        if n.get("archived"):
            continue
        filename = hashlib.sha256(key.encode()).hexdigest()[:24] + ".md"
        exported.add(key)
        def y(field, value):
            return field + ": " + json.dumps(value, ensure_ascii=False) if value else None
        front = ["---", y("type", n.get("kind") or "note"),
                 y("title", n.get("title") or key), y("noosphere_id", key),
                 y("status", n.get("status") or "current"),
                 y("noosphere_recorded_at", n.get("recorded_at") or n.get("created")),
                 y("noosphere_observed_at", n.get("observed_at")),
                 y("noosphere_valid_from", n.get("valid_from")),
                 y("noosphere_valid_to", n.get("valid_to")), "---", "",
                 n.get("body") or "", ""]
        (concepts / filename).write_text("\n".join(x for x in front if x is not None), encoding="utf-8")
        index.append(f'- [{n.get("title") or key}](concepts/{filename})')
    (dest / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    edges = [{"source": s, "target": t, "relation": r, "recorded_at": stamp}
             for (s, t, r), stamp in sorted(links.items()) if s in exported and t in exported]
    (dest / "noosphere-edges.json").write_text(
        json.dumps({"schema": "noosphere-lite.okf-edges.v1", "edges": edges},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"concepts": len(exported), "edges": len(edges),
            "plaintext_export": True, "lossless_roundtrip_claimed": False}

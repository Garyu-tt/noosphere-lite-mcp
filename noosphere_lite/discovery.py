"""Bounded, read-only, conservative cross-memory link *suggestions*.

No model, vector search, personal data exports, or automatic link creation.
A lexical match is only a proposal: never a validated skill transfer or truth.
"""
from __future__ import annotations

from collections import Counter
import math
import re

# Intentionally small multilingual stoplist; no claim of semantic understanding.
STOP = frozenset("""
the and for from this that with into while after before between been have will
was were are not can than what how why when where your their about these those
some other more less does every only also using used same each per one two
его она они это как для что или где про уже надо если еще тоже был есть будут
при какому после перед между свое своих наших можем можно тогда только здесь
там это который которые нужно этих всех через если чтобы когда такой одна
свой свои всего хотя снова друг потому потом иначе будет нужно один два три
project projects system systems model models data results work working note
notes task tasks memory memories information agent agents service services
""".split())


def _terms(value: str) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {x.casefold() for x in re.findall(r"[^\W\d_]{3,}", value, re.UNICODE)
            if x.casefold() not in STOP and len(x) <= 36}


def _features(node: dict) -> tuple[set[str], set[str], set[str]]:
    title=_terms(node.get("title", ""))
    tags=set()
    for tag in node.get("tags", [])[:32]:
        tags.update(_terms(tag))
    # Cheap bounded body scan, never copied into the returned suggestion.
    body=_terms(node.get("body", "")[:1800])
    return title, tags, body


def suggest_links(nodes: dict, links: dict, memory_id: str, limit: int = 10) -> list[dict]:
    """Suggest possible connections, with explanations and unverified status.

    Existing explicit links in either direction, archived records, and the origin
    itself are excluded. The underlying encrypted vault remains unmodified.
    """
    origin=nodes.get(memory_id)
    if origin is None or origin.get("archived"):
        raise KeyError("memory not found")
    budget=max(1,min(int(limit),30))
    eligible={key:node for key,node in nodes.items() if not node.get("archived")}
    if len(eligible)<2:
        return []
    features={key:_features(node) for key,node in eligible.items()}
    # Distinct-document frequency: ubiquitous words have little evidential value.
    freq=Counter()
    for title,tags,body in features.values():
        freq.update(title | tags | body)
    n=len(eligible)
    a_title,a_tags,a_body=features[memory_id]
    origin_terms=a_title|a_tags|a_body
    already={b if a==memory_id else a
             for a,b,_ in links if a==memory_id or b==memory_id}
    found=[]
    for key,node in eligible.items():
        if key==memory_id or key in already:
            continue
        title,tags,body=features[key]
        shared=origin_terms & (title|tags|body)
        # Common background concepts may create surprising amounts of noise.
        rare={w for w in shared if freq[w]<=max(3,n//5)}
        strong=(a_title|a_tags)&(title|tags)
        shared_tags=a_tags & tags
        # At least two *distinct* terms plus a title/tag anchor required.
        # A single tag (e.g. GPU) must not produce a link.
        if len(rare)<2 or not (strong & rare):
            continue
        score=sum((1+math.log1p(n/max(1,freq[w])))*(2 if w in strong else 1)
                  for w in rare)
        if shared_tags:
            score+=3*len(shared_tags)
        if node.get("status")=="stale":
            score*=0.5
        found.append(dict(
            id=key, title=node.get("title",""), kind=node.get("kind","note"),
            status=node.get("status","current"),
            discovery_status="unverified_candidate",
            score=round(score,3),
            shared_terms=sorted(rare)[:12],
            shared_tags=sorted(shared_tags)[:8],
            reason="Lexical overlap; test applicability and provenance before linking."
        ))
    found.sort(key=lambda x:(-x["score"],x["id"]))
    return found[:budget]

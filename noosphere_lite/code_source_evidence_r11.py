"""Fail-closed source freshness annotation for CodeTrace observations.

Roots are caller-supplied trusted configuration, never discovered from indexed
paths. This does not establish runtime compatibility or authorize integration.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from .source_freshness_r08 import classify_trusted_file


def annotate_trace(trace: dict, trusted_projects: dict[str, str], *, max_bytes: int = 2_097_152) -> dict:
    """Return a copy with per-function freshness evidence; no filesystem paths leaked."""
    if not isinstance(trace, dict) or not isinstance(trusted_projects, dict):
        raise TypeError('trace and trusted_projects must be dictionaries')
    functions = trace.get('functions', [])
    if not isinstance(functions, list) or any(not isinstance(f, dict) for f in functions):
        raise ValueError('functions must be a list of dictionaries')
    result = dict(trace)
    enriched = []
    for function in functions:
        item = dict(function)
        project = item.get('project')
        path = item.get('path')
        digest = item.get('source_sha256')
        evidence = {'status': 'unverifiable_untrusted_project', 'runtime_verified': False, 'compatible': None}
        if isinstance(project, str) and project in trusted_projects:
            if isinstance(path, str) and path and not PurePosixPath(path).is_absolute():
                try:
                    evidence = classify_trusted_file(digest, trusted_projects[project], path,
                        observed_at=item.get('observed_at'), max_bytes=max_bytes)
                except (TypeError, ValueError):
                    evidence = {'status': 'unverifiable_invalid_index_record', 'runtime_verified': False, 'compatible': None}
            else:
                evidence = {'status': 'unverifiable_invalid_index_path', 'runtime_verified': False, 'compatible': None}
        item['source_freshness'] = evidence
        enriched.append(item)
    result['functions'] = enriched
    if isinstance(trace.get('root'), dict):
        # Independently verify root: refs are not globally unique across projects,
        # and a bounded functions list may contain a different record with the same ref.
        result['root'] = annotate_trace({'functions': [trace['root']]}, trusted_projects,
                                        max_bytes=max_bytes)['functions'][0]
    result['runtime_verified'] = False
    result['source_freshness_policy'] = 'trusted_project_roots_only; static evidence; fail closed'
    return result

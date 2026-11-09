"""Pure evidence gate for indexed source fingerprints; never executes source."""
from __future__ import annotations
import hashlib
import re

_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def classify_source(indexed_sha256: str | None, current_bytes: bytes | None, *,
                    observed_at: str | None = None) -> dict:
    """Classify evidence without inferring runtime correctness.

    None means source was unavailable, not an empty file. Invalid index
    digests are rejected rather than treated as a mismatch.
    """
    if indexed_sha256 is not None and (not isinstance(indexed_sha256, str)
                                       or not _SHA256.fullmatch(indexed_sha256)):
        raise ValueError("indexed_sha256 must be a 64-character hex digest or None")
    if current_bytes is not None and not isinstance(current_bytes, bytes):
        raise TypeError("current_bytes must be bytes or None")
    if observed_at is not None and not isinstance(observed_at, str):
        raise TypeError("observed_at must be a string or None")
    current = hashlib.sha256(current_bytes).hexdigest() if current_bytes is not None else None
    status = ("unverifiable_missing_index_digest" if indexed_sha256 is None else
              "unverifiable_source_unavailable" if current is None else
              "source_sha256_match" if current == indexed_sha256.lower() else
              "source_sha256_drift")
    return {"status": status, "indexed_sha256": indexed_sha256.lower() if indexed_sha256 else None,
            "current_sha256": current, "indexed_observed_at": observed_at,
            "runtime_verified": False, "compatible": None}

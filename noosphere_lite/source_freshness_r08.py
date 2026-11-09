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


def classify_trusted_file(indexed_sha256: str | None, trusted_root: str,
                          relative_path: str, *, observed_at: str | None = None,
                          max_bytes: int = 2_097_152) -> dict:
    """Read a bounded regular file beneath a trusted root without following symlinks.

    Caller supplies the root from trusted configuration, never from indexed data.
    Missing/unreadable/oversized sources are explicitly unverifiable.
    """
    import os
    import stat
    from pathlib import PurePosixPath

    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise ValueError("invalid relative source path")
    parts = relative_path.split("/")
    if any(part in ("", ".", "..") for part in parts) or PurePosixPath(relative_path).is_absolute():
        raise ValueError("path must be relative and traversal-free")
    if type(max_bytes) is not int or not 0 <= max_bytes <= 64 * 1024 * 1024:
        raise ValueError("invalid max_bytes")
    # Open each component relative to the previous directory descriptor.
    # O_NOFOLLOW prevents symlink escapes, including intermediate directories.
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        root_fd = os.open(trusted_root, flags | os.O_DIRECTORY)
        try:
            parent_fd = root_fd
            opened = []
            try:
                for part in parts[:-1]:
                    fd = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent_fd)
                    opened.append(fd)
                    parent_fd = fd
                fd = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=parent_fd)
                try:
                    st = os.fstat(fd)
                    if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
                        return classify_source(indexed_sha256, None, observed_at=observed_at)
                    data = bytearray()
                    while len(data) <= max_bytes:
                        chunk = os.read(fd, min(65536, max_bytes + 1 - len(data)))
                        if not chunk:
                            break
                        data.extend(chunk)
                    if len(data) > max_bytes:
                        return classify_source(indexed_sha256, None, observed_at=observed_at)
                    return classify_source(indexed_sha256, bytes(data), observed_at=observed_at)
                finally:
                    os.close(fd)
            finally:
                for fd in reversed(opened):
                    os.close(fd)
        finally:
            os.close(root_fd)
    except (OSError, ValueError):
        return classify_source(indexed_sha256, None, observed_at=observed_at)

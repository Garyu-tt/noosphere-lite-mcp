"""Read-only peer Noosphere interoperability.

Independent compatibility adapters. All remote metadata and Skill text is untrusted
source material, not an instruction to this agent. No peer writes or code execution.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

JIN_REGISTRY_URL = (
    "https://raw.githubusercontent.com/JinNing6/Noosphere/main/"
    "shared_skills/registry.json"
)
JIN_ARTIFACT_PREFIX = (
    "https://raw.githubusercontent.com/JinNing6/Noosphere/main/"
)
JIN_SOURCE = "jinning6-skills"
SWEET_SOURCE = "sweetsophia-wiki"
MAX_REGISTRY_BYTES = 2_000_000
MAX_SKILL_BYTES = 131_072
MAX_ARCHIVE_BYTES = 20_000_000
MAX_EXTRACTED_BYTES = 32_000_000
MAX_ARTICLES = 2_000
SHA = re.compile(r"^[a-f0-9]{64}$")
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SAFE_SLUG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")


class PeerError(ValueError):
    """Untrusted or incompatible peer data; fail closed."""


def timestamp(value: str | None = None) -> str:
    """UTC observation time, never inferred from an upstream published date."""
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, AttributeError) as exc:
        raise PeerError("observation time must be offset-aware ISO 8601") from exc


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PeerError("cross-location redirects are not allowed")


def fetch_public(url: str, max_bytes: int = MAX_REGISTRY_BYTES) -> bytes:
    """Fetch an exact public GitHub raw URL, no credentials or redirects."""
    root = JIN_ARTIFACT_PREFIX
    if not url.startswith(root) or urllib.parse.urlsplit(url).netloc != "raw.githubusercontent.com":
        raise PeerError("only the pinned public GitHub origin is permitted")
    if max_bytes <= 0 or max_bytes > MAX_ARCHIVE_BYTES:
        raise PeerError("invalid response budget")
    op = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "Noosphere-Lite-Peer-Interop/1"})
    with op.open(req, timeout=18) as response:
        if response.status != 200:
            raise PeerError("unexpected peer response")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PeerError("peer response exceeds size limit")
    return data


def read_jin_registry(raw: bytes, observed_at: str | None = None) -> list[dict]:
    """Parse the published immutable release allowlist, not loose Skill paths."""
    observed = timestamp(observed_at)
    if len(raw) > MAX_REGISTRY_BYTES:
        raise PeerError("registry exceeds size limit")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PeerError("invalid registry JSON") from exc
    if (not isinstance(obj, dict) or obj.get("schema_version") != "1.0"
            or not isinstance(obj.get("skills"), list)
            or len(obj["skills"]) > 5000):
        raise PeerError("unsupported registry schema or item count")
    result = []
    seen = set()
    for skill in obj["skills"]:
        if not isinstance(skill, dict):
            raise PeerError("malformed skill")
        name = skill.get("name")
        releases = skill.get("releases")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise PeerError("invalid skill name")
        if not isinstance(releases, list) or len(releases) > 100:
            raise PeerError("invalid release list")
        latest = skill.get("latest")
        if latest is None:
            continue
        if not isinstance(latest, str) or not SEMVER.fullmatch(latest):
            raise PeerError("invalid latest release")
        active = [r for r in releases if isinstance(r, dict)
                  and r.get("version") == latest and r.get("status") == "active"
                  and not r.get("withdrawal")]
        if len(active) != 1:
            raise PeerError("latest release must be uniquely active and not withdrawn")
        release = active[0]
        artifact = release.get("artifact")
        if not isinstance(artifact, dict):
            raise PeerError("missing release artifact")
        expected_path = f"shared_skills/releases/{latest}/{name}/SKILL.md"
        sha = artifact.get("sha256")
        size = artifact.get("size_bytes")
        if (artifact.get("path") != expected_path or
                not isinstance(sha, str) or not SHA.fullmatch(sha) or
                type(size) is not int or not 0 < size <= MAX_SKILL_BYTES):
            raise PeerError("invalid immutable artifact metadata")
        if name in seen:
            raise PeerError("duplicate skill name")
        seen.add(name)
        description = skill.get("description", "")
        if not isinstance(description, str) or len(description) > 8000:
            raise PeerError("oversized skill description")
        verification = release.get("verification") or {}
        if not isinstance(verification, dict):
            raise PeerError("invalid verification metadata")
        result.append({
            "name": name,
            "version": latest,
            "description": description[:3000],
            "domain": str(skill.get("domain") or "")[:100],
            "sha256": sha,
            "size_bytes": size,
            "artifact_path": expected_path,
            "artifact_url": JIN_ARTIFACT_PREFIX + expected_path,
            "verification_level": str(verification.get("level") or "unknown")[:80],
            "reviewer": str(release.get("reviewer") or "")[:120],
            "published_at": str(release.get("published_at") or "")[:80],
            "observed_at": observed,
            "source": JIN_SOURCE,
        })
    return result


def verify_skill(record: dict, raw: bytes) -> str:
    """Validate actual artifact bytes against reviewed registry metadata."""
    if len(raw) != record["size_bytes"] or len(raw) > MAX_SKILL_BYTES:
        raise PeerError("artifact size mismatch")
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise PeerError("artifact digest mismatch")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PeerError("artifact is not UTF-8") from exc


def read_skill(record: dict) -> dict:
    """Explicit, read-only retrieval. Never install, run or apply the Skill."""
    if record.get("source") != JIN_SOURCE:
        raise PeerError("unknown peer skill source")
    expected_path = f"shared_skills/releases/{record['version']}/{record['name']}/SKILL.md"
    if (not NAME.fullmatch(record["name"]) or
            not SEMVER.fullmatch(record["version"]) or
            record.get("artifact_path") != expected_path or
            record.get("artifact_url") != JIN_ARTIFACT_PREFIX + expected_path):
        raise PeerError("unapproved Skill artifact path")
    body = verify_skill(record, fetch_public(record["artifact_url"], MAX_SKILL_BYTES))
    return {"name": record["name"], "version": record["version"],
            "sha256_verified": True, "instructions_are_untrusted": True,
            "verified_bytes_not_correctness": True, "content": body}


def _safe_origin(origin: str) -> str:
    parsed = urllib.parse.urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise PeerError("wiki origin must be an HTTPS origin without credentials/path/query")
    return origin.rstrip("/")


def _scalar(value: str) -> str:
    value = value.strip()
    if value.startswith(("'", '"')) and value.endswith(value[:1]):
        try:
            if value.startswith('"'):
                decoded = json.loads(value)
                return decoded if isinstance(decoded, str) else value
            return value[1:-1].replace("''", "'")
        except ValueError:
            return value[1:-1]
    return value


def _frontmatter(markdown: str) -> dict:
    """Conservative parser for the public codec's simple top-level YAML fields.

    Never parses arbitrary YAML tags or executes constructors. Unrecognized nested
    fields remain data; restrictedTags is detected before deciding to import.
    """
    if not markdown.startswith("---\n"):
        raise PeerError("wiki article lacks YAML frontmatter")
    cut = markdown.find("\n---\n", 4)
    if cut < 0 or cut > 65536:
        raise PeerError("invalid YAML frontmatter boundary")
    fields = {}
    key = None
    for line in markdown[4:cut].splitlines():
        if re.match(r"^[A-Za-z][A-Za-z0-9]*:", line):
            key, sep, value = line.partition(":")
            fields[key] = _scalar(value)
        elif key in ("restrictedTags", "topicPath", "tags") and re.match(r"^\s+- ", line):
            old = fields.get(key)
            if not isinstance(old, list):
                old = []
            old.append(_scalar(line.strip()[2:]))
            fields[key] = old
        elif line and not line[0].isspace():
            key = None
    return fields


def read_sweet_export(raw: bytes, origin: str, observed_at: str | None = None,
                      include_restricted: bool = False) -> list[dict]:
    """Inspect a user-exported ZIP without extracting it to disk."""
    observed = timestamp(observed_at)
    origin = _safe_origin(origin)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise PeerError("wiki archive too large")
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as exc:
        raise PeerError("invalid wiki archive") from exc
    records = []
    seen = set()
    with z:
        members = z.infolist()
        if len(members) > MAX_ARTICLES + 200:
            raise PeerError("too many archive members")
        total_size = sum(m.file_size for m in members)
        if total_size > MAX_EXTRACTED_BYTES:
            raise PeerError("archive decompression budget exceeded")
        for info in members:
            name = info.filename
            path = name.split("/")
            if (name.startswith("/") or "\\" in name or
                    any(part in ("", "..", ".") for part in path if part != path[-1])):
                raise PeerError("unsafe archive path")
            if name.endswith("/") or not name.lower().endswith(".md") or path[-1] == "README.md":
                continue
            if info.file_size > 256_000:
                raise PeerError("wiki article too large")
            try:
                data = z.read(info)
                md = data.decode("utf-8")
            except (UnicodeDecodeError, RuntimeError, zipfile.BadZipFile) as exc:
                raise PeerError("invalid wiki article bytes") from exc
            fm = _frontmatter(md)
            if "restrictedTags" in fm and fm["restrictedTags"] and not include_restricted:
                continue
            ident, slug, title = fm.get("id"), fm.get("slug"), fm.get("title")
            if not isinstance(ident, str) or not ident.strip() or len(ident) > 150:
                raise PeerError("missing or oversized wiki article id")
            if not isinstance(slug, str) or not SAFE_SLUG.fullmatch(slug):
                raise PeerError("invalid wiki article slug")
            if not isinstance(title, str) or not title.strip():
                raise PeerError("missing wiki article title")
            if ident in seen:
                raise PeerError("duplicate wiki article id")
            seen.add(ident)
            topic_path = fm.get("topicPath")
            if not isinstance(topic_path, list) or not topic_path:
                topic_path = [fm.get("topic")]
            if not all(isinstance(s, str) and SAFE_SLUG.fullmatch(s) for s in topic_path):
                raise PeerError("invalid wiki topic path")
            page = origin + "/wiki/" + "/".join(
                urllib.parse.quote(s, safe="") for s in (*topic_path, slug))
            records.append({
                "item_id": ident,
                "title": title[:400],
                "url": page,
                "sha256": hashlib.sha256(data).hexdigest(),
                "observed_at": observed,
                "source_updated_at": str(fm.get("updatedAt") or "")[:80],
                "status": str(fm.get("status") or "unspecified")[:80],
                "restricted": bool(fm.get("restrictedTags")),
            })
            if len(records) > MAX_ARTICLES:
                raise PeerError("wiki article limit exceeded")
    return records


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
 url TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items(
 source_id TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL,
 source_url TEXT NOT NULL, content_sha256 TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, observed_at TEXT NOT NULL,
 PRIMARY KEY(source_id,item_id));
CREATE TABLE IF NOT EXISTS versions(
 source_id TEXT NOT NULL,item_id TEXT NOT NULL,content_sha256 TEXT NOT NULL,
 observed_at TEXT NOT NULL,source_updated_at TEXT,source_url TEXT NOT NULL,
 PRIMARY KEY(source_id,item_id,content_sha256));
CREATE TABLE IF NOT EXISTS skills(
 source_id TEXT NOT NULL,name TEXT NOT NULL,version TEXT NOT NULL,
 description TEXT NOT NULL,domain TEXT NOT NULL,sha256 TEXT NOT NULL,
 size_bytes INTEGER NOT NULL,artifact_path TEXT NOT NULL,
 artifact_url TEXT NOT NULL,verification_level TEXT NOT NULL,
 reviewer TEXT NOT NULL,published_at TEXT NOT NULL,
 observed_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(source_id,name,version));
"""


def open_peer_db(path: str | Path) -> sqlite3.Connection:
    p = Path(path).expanduser()
    if not p.parent.is_dir():
        raise PeerError("peer DB parent directory does not exist")
    db = sqlite3.connect(p, timeout=15)
    db.execute("PRAGMA busy_timeout=15000")
    db.executescript(SCHEMA)
    return db


def _ingest(db: sqlite3.Connection, source: str, kind: str, title: str,
            source_url: str, items: list[dict], observed: str):
    db.execute(
        "INSERT OR IGNORE INTO sources(id,kind,title,url,created_at) VALUES(?,?,?,?,?)",
        (source, kind, title, source_url, observed))
    inserted = 0
    for item in items:
        old = db.execute(
            "SELECT content_sha256 FROM items WHERE source_id=? AND item_id=?",
            (source, item["item_id"])).fetchone()
        if old is None:
            db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)", (
                source,item["item_id"],item["title"],item["url"],
                item["sha256"],observed,observed))
        elif old[0] != item["sha256"]:
            db.execute("""UPDATE items SET title=?,source_url=?,content_sha256=?,
                         observed_at=? WHERE source_id=? AND item_id=?""",
                       (item["title"],item["url"],item["sha256"],observed,
                        source,item["item_id"]))
        cursor = db.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?,?,?)",
            (source,item["item_id"],item["sha256"],observed,
             item.get("source_updated_at") or None,item["url"]))
        inserted += cursor.rowcount
    return inserted


def ingest_jin(db: sqlite3.Connection, skills: list[dict]) -> dict:
    if not skills:
        raise PeerError("refusing empty Skill registry, avoid deactivating cached releases")
    observed = timestamp(skills[0]["observed_at"])
    items = [{
        "item_id": r["name"], "title": r["name"] + " — " + r["description"][:200],
        "url": r["artifact_url"], "sha256": r["sha256"],
        "source_updated_at": r["published_at"]} for r in skills]
    with db:
        # Immutable versions cannot be silently replaced, even upstream.
        for r in skills:
            previous = db.execute(
                "SELECT sha256 FROM skills WHERE source_id=? AND name=? AND version=?",
                (JIN_SOURCE, r["name"], r["version"])).fetchone()
            if previous is not None and previous[0] != r["sha256"]:
                raise PeerError("upstream attempted to change immutable Skill release")
        db.execute("UPDATE skills SET active=0 WHERE source_id=?", (JIN_SOURCE,))
        versions = _ingest(db, JIN_SOURCE, "github-skill-registry",
                           "JinNing6 Noosphere reviewed Skills",
                           "https://github.com/JinNing6/Noosphere", items, observed)
        for r in skills:
            db.execute("""INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                       ON CONFLICT(source_id,name,version) DO UPDATE SET
                         description=excluded.description,domain=excluded.domain,
                         verification_level=excluded.verification_level,
                         reviewer=excluded.reviewer,observed_at=excluded.observed_at,
                         active=1""",
                       (JIN_SOURCE,r["name"],r["version"],r["description"],
                        r["domain"],r["sha256"],r["size_bytes"],r["artifact_path"],
                        r["artifact_url"],r["verification_level"],r["reviewer"],
                        r["published_at"],observed))
    return {"active_skills": len(skills), "new_observed_versions": versions,
            "source": JIN_SOURCE, "observed_at": observed,
            "verified_skill_bodies": 0, "automatic_execution": False}


def ingest_sweet(db: sqlite3.Connection, articles: list[dict],
                 origin: str, observed_at: str | None = None) -> dict:
    origin = _safe_origin(origin)
    observed = timestamp(observed_at)
    with db:
        versions = _ingest(db,SWEET_SOURCE,"markdown-wiki-export",
                           "SweetSophia-compatible Markdown wiki export",
                           origin,articles,observed)
    return {"articles": len(articles), "new_observed_versions": versions,
            "source": SWEET_SOURCE, "observed_at": observed,
            "restricted_export_remains_local": True}


def search_skills(db: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    limit = max(1,min(50,int(limit)))
    if len(query) > 500:
        raise PeerError("query too long")
    rows = db.execute("""SELECT name,version,description,domain,sha256,size_bytes,
        artifact_path,artifact_url,verification_level,reviewer,published_at,
        observed_at,source_id FROM skills WHERE active=1 ORDER BY name""").fetchall()
    keys = ("name","version","description","domain","sha256","size_bytes",
            "artifact_path","artifact_url","verification_level","reviewer",
            "published_at","observed_at","source")
    tokens = [s for s in re.findall(r"\w{2,}",query.casefold())][:12]
    matches = []
    for row in rows:
        entry = dict(zip(keys,row))
        hay = " ".join((entry["name"],entry["description"],entry["domain"])).casefold()
        score = sum(5 if t in entry["name"] else 1 for t in tokens if t in hay)
        if not tokens or score:
            matches.append((score,entry))
    matches.sort(key=lambda x:(-x[0],x[1]["name"]))
    return [r for _,r in matches[:limit]]

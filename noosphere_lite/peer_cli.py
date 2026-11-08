"""Explicit owner-run read-only peer sync and archive import CLI."""
import argparse
import json
import sqlite3
from pathlib import Path

from .peer_bridge import (
    JIN_REGISTRY_URL, PeerError, fetch_public, read_jin_registry,
    read_sweet_export, open_peer_db, ingest_jin, ingest_sweet,
    MAX_ARCHIVE_BYTES,
    search_skills, read_skill,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Noosphere peer import: observed metadata, never automatic execution")
    subs = parser.add_subparsers(dest="command", required=True)
    jin = subs.add_parser("sync-skills", help="explicitly fetch public GitHub registry")
    jin.add_argument("--db", required=True, type=Path)
    jin.add_argument("--registry-file", type=Path,
                     help="offline registry fixture instead of live GitHub")
    sweet = subs.add_parser("import-wiki", help="local SweetSophia /api/export ZIP")
    sweet.add_argument("--db", required=True, type=Path)
    sweet.add_argument("--zip", required=True, type=Path)
    sweet.add_argument("--origin", required=True,
                       help="actual HTTPS origin of exported wiki instance")
    sweet.add_argument("--include-restricted", action="store_true",
                       help="explicit local-only opt-in for restricted wiki metadata")
    search = subs.add_parser("skills", help="read local cached registry metadata")
    search.add_argument("--db", required=True, type=Path)
    search.add_argument("--query", default="")
    search.add_argument("--limit", type=int, default=10)
    get = subs.add_parser("skill", help="explicitly retrieve SHA256-verified Skill text")
    get.add_argument("--db", required=True, type=Path)
    get.add_argument("--name", required=True)
    get.add_argument("--version", help="optional exact release version")
    args = parser.parse_args()
    try:
        if args.command == "sync-skills":
            raw = (args.registry_file.read_bytes() if args.registry_file
                   else fetch_public(JIN_REGISTRY_URL))
            skills = read_jin_registry(raw)
            with open_peer_db(args.db) as db:
                receipt = ingest_jin(db, skills)
            print(json.dumps(receipt, indent=2))
        elif args.command == "import-wiki":
            if args.zip.stat().st_size > MAX_ARCHIVE_BYTES:
                raise PeerError("wiki archive exceeds size limit")
            articles = read_sweet_export(args.zip.read_bytes(), args.origin,
                                         include_restricted=args.include_restricted)
            with open_peer_db(args.db) as db:
                receipt = ingest_sweet(db, articles, args.origin)
            print(json.dumps(receipt, indent=2))
        elif args.command in ("skills", "skill"):
            # Read-only connection: no initialization or other DB writes.
            uri = f"file:{args.db.resolve()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as db:
                if args.command == "skills":
                    results = search_skills(db, args.query, args.limit)
                    print(json.dumps(results, indent=2, ensure_ascii=False))
                else:
                    records = [r for r in search_skills(db, "", 50)
                               if r["name"] == args.name
                               and (not args.version or r["version"] == args.version)]
                    if len(records) != 1:
                        raise PeerError("Skill not in the active local registry")
                    print(json.dumps(read_skill(records[0]), ensure_ascii=False, indent=2))
    except (PeerError, OSError, sqlite3.DatabaseError) as exc:
        parser.exit(2, f"Peer interoperability error: {exc}\n")


if __name__ == "__main__":
    main()

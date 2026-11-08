"""Use python -m noosphere_lite init | status | mcp."""
import argparse
import os
import re
from pathlib import Path
from .vault import MemoryVault, VaultError

_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}\Z")


def bound_project():
    """Deployment-controlled process identity, never an MCP tool argument."""
    project = os.environ.get("NSL_BOUND_PROJECT")
    if project is None:
        return None
    if not _PROJECT.fullmatch(project):
        raise VaultError("invalid NSL_BOUND_PROJECT (1..48 path-safe characters)")
    return project


def reject_bound_path_overrides(project, *, primary=None, mirror=None, key_file=None):
    """Never allow a scoped process to point to the unscoped/another vault."""
    if project is not None and any(x is not None for x in (primary, mirror, key_file)):
        raise VaultError("bound project forbids explicit vault path overrides")


def config():
    home = Path.home()
    primary = Path(os.environ.get("NSL_PRIMARY", str(home / ".local/share/noosphere-lite")))
    mirror = Path(os.environ.get("NSL_MIRROR", str(home / ".local/share/noosphere-lite-mirror")))
    key = Path(os.environ.get("NSL_KEY_FILE", str(home / ".config/noosphere-lite/key")))
    project = bound_project()
    if project is None:
        return primary, mirror, key
    # The source paths become BASES for independent project-specific journals
    # and keys. No existing unscoped journal is opened or migrated.
    return (primary / "projects" / project,
            mirror / "projects" / project,
            key.parent / "projects" / project / key.name)

def main():
    parser = argparse.ArgumentParser(description="Noosphere Lite MCP local encrypted memory")
    parser.add_argument("command", choices=["init", "status", "mcp"])
    parser.add_argument("--primary", type=Path)
    parser.add_argument("--mirror", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--development-same-device", action="store_true",
                        help="INSECURE FOR RESILIENCE: bypass independent-filesystem requirement")
    args = parser.parse_args()
    try:
        project = bound_project()
        reject_bound_path_overrides(project, primary=args.primary,
                                    mirror=args.mirror, key_file=args.key_file)
        env_primary, env_mirror, env_key = config()
        store = MemoryVault(args.primary or env_primary,
                            args.mirror or env_mirror,
                            args.key_file or env_key,
                            allow_same_device=args.development_same_device or
                            os.environ.get("NSL_DEVELOPMENT_SAME_DEVICE") == "1")
        if args.command == "init":
            store.initialize()
            print("Initialized two AES-256-GCM journals. Back up the key OFFLINE.")
        elif args.command == "status":
            print(store.status())
        else:
            from .mcp_server import run
            run(store, bound_project=project)
    except VaultError as exc:
        parser.exit(2, f"Vault error: {exc}\n")

if __name__ == "__main__":
    main()


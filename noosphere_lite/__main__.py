"""Use python -m noosphere_lite init | status | mcp."""
import argparse
import os
from pathlib import Path
from .vault import MemoryVault, VaultError

def config():
    home = Path.home()
    return (
        Path(os.environ.get("NSL_PRIMARY", str(home / ".local/share/noosphere-lite"))),
        Path(os.environ.get("NSL_MIRROR", str(home / ".local/share/noosphere-lite-mirror"))),
        Path(os.environ.get("NSL_KEY_FILE", str(home / ".config/noosphere-lite/key"))),
    )

def main():
    parser = argparse.ArgumentParser(description="Noosphere Lite MCP local encrypted memory")
    parser.add_argument("command", choices=["init", "status", "mcp"])
    parser.add_argument("--primary", type=Path)
    parser.add_argument("--mirror", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--development-same-device", action="store_true",
                        help="INSECURE FOR RESILIENCE: bypass independent-filesystem requirement")
    args = parser.parse_args()
    env_primary, env_mirror, env_key = config()
    store = MemoryVault(args.primary or env_primary,
                        args.mirror or env_mirror,
                        args.key_file or env_key,
                        allow_same_device=args.development_same_device or
                        os.environ.get("NSL_DEVELOPMENT_SAME_DEVICE") == "1")
    try:
        if args.command == "init":
            store.initialize()
            print("Initialized two AES-256-GCM journals. Back up the key OFFLINE.")
        elif args.command == "status":
            print(store.status())
        else:
            from .mcp_server import run
            run(store)
    except VaultError as exc:
        parser.exit(2, f"Vault error: {exc}\n")

if __name__ == "__main__":
    main()


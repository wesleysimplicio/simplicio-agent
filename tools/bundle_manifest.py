#!/usr/bin/env python3
"""Create and verify deterministic manifests for versioned Agent bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

MANIFEST = Path("manifests/bundle.json")
CHECKSUMS = Path("manifests/checksums.txt")
EXCLUDED = {MANIFEST, CHECKSUMS}


def files_for(root: Path) -> list[Path]:
    return sorted(
        p.relative_to(root)
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root) not in EXCLUDED
        and not str(p.relative_to(root)).startswith("manifests/signatures/")
    )


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def create(root: Path, source_commit: str, version: str, signing_key: str | None) -> None:
    manifest = root / MANIFEST
    checksums = root / CHECKSUMS
    manifest.parent.mkdir(parents=True, exist_ok=True)
    entries = [(str(path), digest(root / path)) for path in files_for(root)]
    signature = {"status": "unsigned", "verification": "sha256-only"}
    minisign = None
    sig_path = root / "manifests/signatures/bundle.json.minisig"
    if signing_key:
        minisign = which("minisign")
        if not minisign:
            raise SystemExit("signing requested but minisign is unavailable")
        signature = {"status": "minisign", "artifact": str(sig_path)}
    payload = {
        "schema": 1,
        "version": version,
        "source_commit": source_commit,
        "files": [{"path": path, "sha256": sha} for path, sha in entries],
        "signature": {"status": "unsigned", "verification": "sha256-only"},
    }
    # Stable JSON and no wall-clock field make repeated builds from one commit comparable.
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Include the manifest itself so unsigned verification still detects metadata changes.
    all_entries = entries + [(str(MANIFEST), digest(manifest))]
    checksums.write_text("".join(f"{sha}  {path}\n" for path, sha in all_entries), encoding="utf-8")
    if signing_key:
        sig_path.parent.mkdir(parents=True, exist_ok=True)
        generated = manifest.with_suffix(manifest.suffix + ".minisig")
        assert minisign is not None
        subprocess.run(
            [minisign, "-Sm", str(manifest), "-s", signing_key, "-W"],
            check=True,
            stdin=subprocess.DEVNULL,
        )
        generated.replace(sig_path)
        checksums.write_text(
            "".join(f"{sha}  {path}\n" for path, sha in entries)
            + f"{digest(manifest)}  {MANIFEST}\n",
            encoding="utf-8",
        )
    print(f"manifest: {len(entries)} files, signature={payload['signature']['status']}")


def verify(root: Path) -> None:
    manifest_path = root / MANIFEST
    checksums_path = root / CHECKSUMS
    if not manifest_path.is_file() or not checksums_path.is_file():
        raise SystemExit("bundle is missing manifests/bundle.json or manifests/checksums.txt")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["path"]: item["sha256"] for item in payload.get("files", [])}
    expected[str(MANIFEST)] = digest(manifest_path)
    actual = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sha, path = line.split("  ", 1)
        actual[path] = sha
    if expected != actual:
        raise SystemExit("manifest/checksum index mismatch")
    present = {str(path): digest(root / path) for path in files_for(root)}
    present[str(MANIFEST)] = digest(manifest_path)
    if present != expected:
        missing = sorted(set(expected) - set(present))
        extra = sorted(set(present) - set(expected))
        changed = sorted(path for path in set(expected) & set(present) if expected[path] != present[path])
        raise SystemExit("bundle verification failed: " + ", ".join([f"missing={missing}", f"extra={extra}", f"changed={changed}"]))
    print(f"verified: {payload.get('version', '<unknown>')} ({len(expected)} files; {payload.get('signature', {}).get('verification', 'unknown')})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "verify"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--version", default="")
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--signing-key")
    args = parser.parse_args()
    if args.command == "create":
        create(args.root, args.source_commit, args.version, args.signing_key)
    else:
        verify(args.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())

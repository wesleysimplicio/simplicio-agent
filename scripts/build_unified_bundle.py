#!/usr/bin/env python3
"""Unified Distribution Packaging Helper (refs #50).

Builds an immutable, versioned bundle layout for the ``simplicio``/``hermes``
distribution and emits the supporting integrity + update artifacts that the
unified distribution channel (Homebrew, cargo, pip, single binary) consumes.

The layout produced under ``dist/bundle/<version>/`` is deterministic and
content-addressed so it can be published as-is to GitHub Releases and mirrored
by package managers:

    dist/bundle/<version>/
        SHA256SUMS            # sha256 digest per artifact (sha256sum format)
        manifest.json         # unified update manifest (version + artifacts)
        artifacts/            # the collected/staged release artifacts

Usage:
    # Preview what would be staged (no files written)
    python scripts/build_unified_bundle.py --dry-run

    # Build the bundle for the current pyproject version
    python scripts/build_unified_bundle.py

    # Override version / add extra artifacts (e.g. built binaries)
    python scripts/build_unified_bundle.py --version 0.25.0 \
        --artifact dist/simplicio-macos-arm64 \
        --artifact dist/simplicio-linux-x64

Signing (Ed25519, optional): if ``--sign-key`` points at a raw 32-byte Ed25519
private key, ``SHA256SUMS`` is signed and ``SHA256SUMS.sig`` is written next to
it. Signing degrades gracefully to a no-op (with a warning) when the key is
absent, so the helper stays usable in un-keyed CI dry runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"
DEFAULT_BUNDLE_ROOT = REPO_ROOT / "dist" / "bundle"


def read_version() -> str:
    """Read the project version from pyproject.toml."""
    text = PYPROJECT_FILE.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("could not find version in pyproject.toml")
    return match.group(1)


def sha256_file(path: Path) -> str:
    """Return the hex sha256 digest of a file, streaming to bound memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sign_sha256sums(sums_file: Path, key_path: Path) -> Path | None:
    """Sign SHA256SUMS with a raw Ed25519 private key, if available.

    Returns the signature path on success, or None when signing is skipped.
    """
    if not key_path.exists():
        print(f"warning: sign key {key_path} not found; skipping Ed25519 signature")
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError:
        print("warning: 'cryptography' not installed; skipping Ed25519 signature")
        return None

    raw = key_path.read_bytes()
    if len(raw) != 32:
        raise SystemExit(
            f"sign key must be a raw 32-byte Ed25519 seed, got {len(raw)} bytes"
        )
    private_key = Ed25519PrivateKey.from_private_bytes(raw)
    signature = private_key.sign(sums_file.read_bytes())
    sig_path = sums_file.with_suffix(sums_file.suffix + ".sig")
    sig_path.write_bytes(signature)
    return sig_path


def build_bundle(
    version: str,
    artifacts: list[Path],
    bundle_root: Path,
    sign_key: Path | None,
    dry_run: bool,
) -> Path:
    """Stage artifacts into the immutable bundle layout and emit integrity files."""
    bundle_dir = bundle_root / version
    artifacts_dir = bundle_dir / "artifacts"

    print(f"bundle version : {version}")
    print(f"bundle dir     : {bundle_dir}")
    print(f"artifacts      : {len(artifacts)}")

    if dry_run:
        for artifact in artifacts:
            status = "ok" if artifact.exists() else "MISSING"
            print(f"  [{status}] {artifact}")
        print("dry-run: no files written")
        return bundle_dir

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    staged: list[Path] = []
    for artifact in artifacts:
        if not artifact.exists():
            raise SystemExit(f"artifact not found: {artifact}")
        target = artifacts_dir / artifact.name
        shutil.copy2(artifact, target)
        staged.append(target)

    # SHA256SUMS in canonical `sha256sum` format (digest + two spaces + name).
    sums_lines = []
    manifest_artifacts = []
    for target in sorted(staged, key=lambda p: p.name):
        digest = sha256_file(target)
        rel = target.relative_to(bundle_dir).as_posix()
        sums_lines.append(f"{digest}  {rel}")
        manifest_artifacts.append(
            {
                "name": target.name,
                "path": rel,
                "size": target.stat().st_size,
                "sha256": digest,
            }
        )

    sums_file = bundle_dir / "SHA256SUMS"
    sums_file.write_text("\n".join(sums_lines) + ("\n" if sums_lines else ""), encoding="utf-8")

    sig_path = None
    if sign_key is not None:
        sig_path = sign_sha256sums(sums_file, sign_key)

    manifest = {
        "schema": "simplicio.dist-manifest/v1",
        "name": "simplicio-agent",
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sha256sums": "SHA256SUMS",
        "signature": sig_path.name if sig_path else None,
        "artifacts": manifest_artifacts,
    }
    manifest_file = bundle_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {sums_file}")
    print(f"wrote {manifest_file}")
    if sig_path:
        print(f"wrote {sig_path}")
    return bundle_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None, help="override bundle version")
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        dest="artifacts",
        help="path to a release artifact to include (repeatable)",
    )
    parser.add_argument(
        "--bundle-root",
        default=str(DEFAULT_BUNDLE_ROOT),
        help="root directory for versioned bundles (default: dist/bundle)",
    )
    parser.add_argument(
        "--sign-key",
        default=None,
        help="path to a raw 32-byte Ed25519 private key for SHA256SUMS.sig",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be staged without writing files",
    )
    args = parser.parse_args(argv)

    version = args.version or read_version()
    artifacts = [Path(a).resolve() for a in args.artifacts]
    bundle_root = Path(args.bundle_root).resolve()
    sign_key = Path(args.sign_key).resolve() if args.sign_key else None

    build_bundle(version, artifacts, bundle_root, sign_key, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

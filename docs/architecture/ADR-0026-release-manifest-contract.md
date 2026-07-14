# ADR-0026: digest-pinned release and rollback contract

`tools/release_manifest.py` defines a local, content-addressed release gate.
The `simplicio-agent` artifact, `simplicio-runtime`, and every listed file use
`sha256:` digests; the manifest digest covers all manifest fields except itself.
Validation fails closed on legacy identities, malformed digests, duplicate
files, or mismatched content.

Rollback evidence must preserve state, include receipts, and pin the restored
`simplicio-agent` manifest digest.  These contracts prove local metadata
integrity only; publication, clean-machine installation, and live activation
remain separate release evidence.

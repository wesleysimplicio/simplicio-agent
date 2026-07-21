# ADR-0021: Verified Runtime lock contract

The agent validates a versioned Runtime lock independently of the existing
runtime manager. A target must have an HTTPS asset URL, strict version, target
metadata, positive size, and SHA-256. A local artifact is never executed by
this validator; when supplied, its bytes are checked before readiness.

`stable_ready` is false unless the metadata is structurally valid, the selected
asset is at least `min_version`, any explicit release tag in its URL matches
the asset version, and the provenance declares
`signature_status=verified`. The runtime manager now gates both readiness and
download on `stable_ready`, so `not-proven`, revoked, or malformed provenance
cannot reach a Runtime handshake.

This slice does not download release assets or prove GitHub signatures; the
committed lock remains unchanged when no signed artifact is available. Those
release/clean-machine artifacts are `UNVERIFIED` and remain tracked by issue
#127.

# ADR-0021: Verified Runtime lock contract

The agent validates a versioned Runtime lock independently of the existing
runtime manager. A target must have an HTTPS asset URL, strict version, target
metadata, positive size, and SHA-256. A local artifact is never executed by
this validator; when supplied, its bytes are checked before readiness.

`stable_ready` is false unless the metadata is structurally valid and the
provenance declares `signature_status=verified`. This slice does not download
release assets or prove GitHub signatures; those remain release/clean-machine
work tracked by issue #127.

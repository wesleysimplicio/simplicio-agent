# ADR-0034: signed delivery-ledger boundary

**Status:** Accepted as a bounded slice for issue #24 (2026-07-21).

## Decision

Extend the existing `simplicio.delivery-ledger/v1` hash-linked certificate
ledger with optional Ed25519 signatures. A caller supplies an installation or
operator private key at process scope; the ledger serializes only the raw
public key, optional signer label, and signature. The private key is never
written by this module or committed to the repository.

`verify_ledger` recomputes certificate hashes, entry hashes, previous-hash
links, and every available signature without trusting the stored verdict. The
JSONL `SignedLedgerStore` writes rows by atomic replacement and refuses to
append to a chain that does not verify. A caller can pass
`require_signatures=True` to reject legacy unsigned rows. The default in the
existing in-memory API keeps unsigned ledgers readable; the durable store is
strict by default.

The local `tools.anti_fake_gate` scanner adds a deliberately conservative AST
check for silent function bodies and exact synthetic-success placeholders. It
is evidence for the bounded local gate, not a claim that semantic fakery is
fully decidable.

## Deliberate limits

This slice is local cryptographic evidence only. It does not invoke the
Simplicio Runtime `deliver check`/`regression`/`certify` producer, persist keys,
wire the conversation close path, connect Runtime producer certificates, or
claim the full issue acceptance criteria. Those remain follow-up integrations.

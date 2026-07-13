# Wormhole Codec + DBBH Prism — Integração

Adicionados em 2026-07-04 como workspace members do simplicio-runtime.
Dois crates do JesseBrown1980, zero deps, HBP json=0.

## holographic-wormhole-codec (crates/wormhole-codec/)

O unified DBBH -> DBWH throat, um loop testado:

```
BLACK MOUTH   black_hole_compress: object -> N-cylinder shadows + AGT + IX-737 capsule
THROAT        o que cruza = capsule + residual selector, NÃO o objeto
WHITE MOUTH   white_hole_emit: consent-gated reconstruct (CRT), AGT round-trip
WATCHER       N-directional gate: AGT round-trip + N-cylinder cross-checks
RECEIPT       HBP hot-path rows -> VerifiedClone | Held
```

### Tipos chave
- `WormholePacket` — shadows + AGT + roof + capsule
- `SessionCapsule` — nonce 8-byte, bilateral arm, single-use
- `Verdict` — VerifiedClone(Vec<u8>) | Held(Held)
- `NQPrismNexus` — uniform room: Host8 + BH prefix + shadows + all rungs
- `BehcsRung` — B64/B256/B1024/Hyper

### Funções
- `black_hole_compress(obj, sender, receiver, salt) -> WormholePacket`
- `white_hole_emit(pkt, subset) -> Verdict` (consent-gated)
- `wormhole_traverse(obj, recover_with, cross) -> Verdict`
- `nexus_ladder_traverse(obj, &[rungs]) -> Option<Vec<u8>>`
- `NQPrismNexus::absorb(obj) -> NQPrismNexus`

### Testes (7)
- nqprism_nexus_is_the_uniform_room
- nexus_ladder_is_uniform_bijective_lossless
- nexus_receipt_json0
- sha256_kat
- full_throat_verifies_clone_byte_identical
- insufficient_roof_holds
- white_mouth_needs_consent_and_respects_collapse
- watcher_catches_tampered_shadow_via_address_and_crosscheck
- roof_rises_and_receipt_is_hotpath_json0

## dbbh-coms-quant-prism (crates/dbbh-prism/)

Primeira célula do Prisma Quântico de Comunicação DBBH.

### BEHCS Ladder (Groupoid de bijeções)
- `Level::Behcs64` — 6-bit symbols (0..63)
- `Level::Behcs256` — bytes (0..255) 
- `Level::Behcs1024` — 10-bit glyphs (0..1023)
- `HyperBEHCS(60D)` — 1024-glyph shadow reshaped em 60D tuples

Cada rung é lossless (`H(f(X)) = H(X)`). Composição de bijeções = bijeção.

### Q-PRISM Cube
PID-specific 60D selector sobre o shadow 1024-glyph do conteúdo.
`QPrismCube::new(pid, content)` — derive_selector é sha256(pid || counter || content).

### IX-737 Capsule
Consentimento bilateral: sender + receiver precisam armar.
Single-use nonce, append-only audit chain (ReceiptChain).
Estados: Proposed -> Armed -> Collapsed | Revoked.

### Coms Flow
- `dbbh_send(cube, capsule) -> Result<Crossing, Held>`
- `dbbh_receive(crossing, capsule) -> Result<Vec<u8>, Held>`
- `dbbh_send_addressed(cube, capsule) -> Crossing` (address-only, sem payload)
- `dbbh_receive_addressed(crossing, capsule, store) -> Result<Vec<u8>, Held>`

### ContentStore
`HashMap<String, Vec<u8>>` — AGT -> content. Put retorna AGT, get por AGT.

### Testes (19 total)
- sha256_kat, ladder_roundtrip_all_rungs
- behcs256_1024_reference_rung_5bytes_4glyphs
- groupoid_path_independence
- hyperbehcs_60d_reshape_roundtrip
- cube_is_pid_specific_and_lossless
- capsule_needs_both_sides_to_open
- receipt_chain_verifies_and_detects_tamper
- + tests/integration.rs, tests/suite.rs, tests/system.rs

## Bridge no runtime

```rust
use crate::asolaria::wormhole_bridge::*;  // holographic_wormhole_codec re-export
use crate::asolaria::prism_bridge::*;      // dbbh_coms_quant_prism re-export

// Uso: wormhole traverse com watcher gate
let result = wormhole_traverse(b"meus dados", &[0, 1], &[2, 3]);
match result {
    Verdict::VerifiedClone(data) => println!("Clone verificado: {} bytes", data.len()),
    Verdict::Held(reason) => println!("Retido: {:?}", reason),
}

// Uso: capsule com consentimento bilateral
let mut cap = SessionCapsule::propose(sender, receiver, ComsMode::AiToAi, b"salt");
cap.arm(sender);
cap.arm(receiver);  // só abre quando ambos armarem
let cube = QPrismCube::new(pid, content);
let crossing = dbbh_send(&cube, &mut cap).unwrap();
```

## PRs

- #2918: feat(asolaria): integrate HBI/HBP bridge (#2918)
- #2919: feat(asolaria): integra wormhole-codec + dbbh-quant-prism
- 54fece46: feat(asolaria): bridges wormhole e DBBH prism no modulo asolaria

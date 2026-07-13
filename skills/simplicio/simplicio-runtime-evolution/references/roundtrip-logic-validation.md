# Validate transcoding/encoding logic in Python BEFORE editing Rust

## When to use
Any change to a byte<->symbol / encode<->decode / round-trip codec in Rust
(`glyph_genesis.rs`, `behcs.rs`, `hyper_behcs.rs`, compression crates).
Compile-fix-iterate on Rust is slow (cargo rebuild) and the bug surface is
pure algorithmic (endianness, padding, group boundaries).

## Technique (session 2026-07-11, glyph_genesis round-trip)
1. Write a Python replica of the exact algorithm (functions + bit math).
2. Iterate the algorithm in Python (instant feedback, no compile) until
   round-trip is byte-exact on a VECTOR of inputs.
3. Only then transplant the validated logic into Rust via `simplicio edit --plan`.
4. Run `cargo test --lib <module>` to confirm the real tests pass.

## Why guess-fixing Rust fails here
The original glyph_genesis bug: `val <<= shift` padded short groups, but the
encoder then emitted `val % 1024` first (least-significant symbol) — for a
short group `shift` pushed the data into bits that `% 1024` reads as zero, so
the byte was LOST. Three Rust edits guessed wrong before the Python prototype
revealed the real invariant: emit `ceil(c*8/10)` symbols for a short group
(NO padding), and have the decoder read `src_bytes = (glen*10)//8` for a short
trailing group (`glen < 4`).

## Test vectors that MUST be covered (short final group is where it breaks)
- final group 1 byte: `list(range(0,41))`, `[1]`
- final group 2 bytes: `[1,2]`
- final group 3 bytes: `[1,2,3]`
- all-full groups (5 bytes): `list(range(0,100))`, `[0xFF]*5`
- empty: `[]`
Covering only full groups (the common case) hides the bug; the failure is
ALWAYS in the truncated final group.

## Recipe
```python
def enc(data): ...      # mirror Rust transcode_256_1024
def dec(syms): ...      # mirror Rust transcode_1024_to_256
for t in vectors:
    assert dec(enc(t)) == t, (t, dec(enc(t)))
```
When all vectors pass, transplant. Keep the Python file in `/tmp` (throwaway) —
do not commit it.

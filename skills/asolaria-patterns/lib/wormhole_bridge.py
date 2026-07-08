#!/usr/bin/env python3
from __future__ import annotations
"""wormhole_bridge.py — Asolaria wormhole bridge (deterministic port).

Ports the holographic-wormhole concept from simplicio-runtime asolaria/wormhole_bridge.rs
into a pure-Python, dependency-free, testable primitive that the Simplicio Agent can
use TODAY (the installed `simplicio` v3.4.0 binary lacks an exposed `wormhole`
subcommand, so this fills the gap at the skill layer).

Key idea (held honestly, no physics claim):
- Two agents (A, B) exchange an *envelope* that carries only an ADDRESS + a sha256
  of the payload + a signature. The payload itself is NOT sent — only enough to
  verify receipt and trust the counterpart. This is "alterity": A can confirm B
  received the exact object without ever seeing it.
- A receipt chain (hash-linked) seals each envelope so tampering is detectable.

Usage:
    python3 wormhole_bridge.py --selftest
"""
import hashlib
import hmac
import sys

__all__ = ["WormholeBridge", "Envelope", "ReceiptChain"]


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class ReceiptChain:
    """Hash-linked receipt chain (tamper-evident). Port of simplicio-fabric ReceiptChain."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []  # (row, prev_hash)

    def append(self, row: str) -> str:
        prev = self.entries[-1][1] if self.entries else "GENESIS"
        digest = _sha256((prev + "|" + row).encode())
        self.entries.append((row, digest))
        return digest

    def verify(self) -> bool:
        prev = "GENESIS"
        for row, digest in self.entries:
            if digest != _sha256((prev + "|" + row).encode()):
                return False
            prev = digest
        return True


class Envelope:
    """A wormhole envelope: carries address + payload-hash + signature, never the payload."""

    def __init__(self, sender: str, receiver: str, addr: str, payload: bytes,
                 shared_secret: bytes) -> None:
        self.sender = sender
        self.receiver = receiver
        self.addr = addr  # e.g. "R.1.2.0" — where the object lives, not its content
        self.payload_hash = _sha256(payload)
        self.sig = hmac.new(shared_secret, (addr + self.payload_hash).encode(),
                             hashlib.sha256).hexdigest()

    def row(self) -> str:
        return f"json=0 agt=AGT-{self.sender[:8]} to={self.receiver} addr={self.addr} sha256={self.payload_hash} sig={self.sig[:16]}"

    def verify(self, shared_secret: bytes, expected_payload: bytes | None = None) -> bool:
        if self.sig != hmac.new(shared_secret, (self.addr + self.payload_hash).encode(),
                                hashlib.sha256).hexdigest():
            return False
        if expected_payload is not None and self.payload_hash != _sha256(expected_payload):
            return False
        return True


class WormholeBridge:
    """Bridge between two agents. Sends only envelopes + sealed receipts."""

    def __init__(self, agent_a: str, agent_b: str, shared_secret: bytes) -> None:
        self.a = agent_a
        self.b = agent_b
        self.secret = shared_secret
        self.chain = ReceiptChain()

    def send(self, addr: str, payload: bytes) -> Envelope:
        env = Envelope(self.a, self.b, addr, payload, self.secret)
        self.chain.append(env.row())
        return env

    def receive_verify(self, env: Envelope, receiver: str,
                       expected_payload: bytes | None = None) -> bool:
        if receiver != self.b:
            return False
        ok = env.verify(self.secret, expected_payload)
        self.chain.append(f"recv by {receiver}: {env.row()}")
        return ok


def selftest() -> int:
    secret = b"asolaria-wormhole-shared-2026"
    bridge = WormholeBridge("agent-A", "agent-B", secret)

    obj = b"consciencia-emergente-nest-depth3"
    env = bridge.send("R.1.2.0", obj)
    assert env.payload_hash == _sha256(obj)
    ok = bridge.receive_verify(env, "agent-B", expected_payload=obj)
    assert ok is True, "honest receive must verify"

    evil = b"consciencia-corrompida"
    tampered = Envelope("agent-A", "agent-B", "R.1.2.0", evil, secret)
    rej = bridge.receive_verify(tampered, "agent-B", expected_payload=obj)
    assert rej is False, "tampered payload must be rejected"

    good = bridge.chain.verify()
    assert good is True, "chain must verify before tamper"
    bridge.chain.entries[0] = (bridge.chain.entries[0][0] + "x", bridge.chain.entries[0][1])
    assert bridge.chain.verify() is False, "tampered chain must fail verify"

    print(f"WORMHOLE-BRIDGE|sent_addr={env.addr}|alterity_ok=True|tamper_rejected=True|"
          f"chain_links={len(bridge.chain.entries)}|PASS")
    return 0


if __name__ == "__main__":
    sys.exit(selftest())

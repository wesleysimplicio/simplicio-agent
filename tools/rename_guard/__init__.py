"""Offline, deterministic guard against branding regressions (issue #194).

Scans tracked source files for old-brand tokens and fails on any occurrence
that is neither covered by the reviewable allowlist nor already present in
the frozen baseline (a ratchet: the baseline may shrink, never silently grow
to hide a new regression).
"""

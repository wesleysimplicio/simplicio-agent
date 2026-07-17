"""Fault-injection coverage for tools/transaction_primitives.py (#338).

These tests kill a real child *process* mid-write (SIGKILL on POSIX,
TerminateProcess via Python's default on Windows) at the journal-append
boundary and prove the journal recovers cleanly afterwards: the truncated
tail is detected and ignored, and subsequent appends produce a valid,
replayable hash chain.  This is deliberately a real subprocess kill, not a
simulated truncation, so it exercises the actual crash-recovery contract
called out in the issue's acceptance criteria ("SIGKILL injetado ... deixa
o sistema restaurável").
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.transaction_primitives import TransactionJournal, JournalError

_CHILD_SCRIPT = """
import os
import sys
import time

path = sys.argv[1]
# Open in append mode and write a well-formed JSON record's *prefix* only,
# then flush and idle so the parent can SIGKILL/terminate this process
# mid-record -- reproducing a crash between os.write() calls in
# TransactionJournal.append().
partial = b'{"schema":"simplicio.journal/v1","sequence":2,"event":"mutation"'
with open(path, "ab") as handle:
    handle.write(partial)
    handle.flush()
    os.fsync(handle.fileno())
    print("READY", flush=True)
    time.sleep(30)
"""


def _seed_one_valid_record(path: Path) -> TransactionJournal:
    journal = TransactionJournal(path)
    journal.append("stage", {"snapshot": "a" * 64})
    return journal


def test_sigkill_mid_journal_write_leaves_journal_restorable(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    journal = _seed_one_valid_record(path)
    before_kill = journal.records()
    assert len(before_kill) == 1

    script = tmp_path / "crash_writer.py"
    script.write_text(_CHILD_SCRIPT, encoding="utf-8")

    process = subprocess.Popen(
        [sys.executable, str(script), str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stdout.readline()
        assert line.strip() == "READY", f"child did not signal readiness: {line!r}"
        # Give the OS a moment to have fully flushed/fsynced the partial
        # record before we kill -- we want a real torn-write on disk, not a
        # race against buffered I/O.
        time.sleep(0.2)
    finally:
        process.kill()  # SIGKILL on POSIX; TerminateProcess on Windows
        process.wait(timeout=10)

    raw = path.read_bytes()
    assert not raw.endswith(b"\n"), "fixture must leave a truncated tail on disk"

    # 1. Reading after the crash must not raise, and must not resurrect the
    #    partial record -- only the previously committed record survives.
    recovered_journal = TransactionJournal(path)
    survivors = recovered_journal.records()
    assert len(survivors) == 1
    assert survivors[0].event == "stage"

    # 2. The journal must remain writable and produce a valid, replayable
    #    hash chain after the crash (this exercises _discard_partial_tail's
    #    truncate-and-continue path via a real killed process, not a
    #    hand-crafted byte string).
    recovered_journal.append("commit", {"snapshot": "a" * 64})
    final = recovered_journal.records()
    assert [r.event for r in final] == ["stage", "commit"]
    assert [r.sequence for r in final] == [1, 2]

    # 3. The recovered file must contain no trace of the killed process's
    #    dangling "mutation" event -- proving truncation, not silent repair.
    assert b'"mutation"' not in path.read_bytes()


def test_journal_recovers_from_process_crash_repeated_across_boundaries(
    tmp_path: Path,
):
    """A second boundary: crash immediately after the very first append,
    i.e. journal file does not exist yet at kill time, then a fresh writer
    must be able to create it from scratch without inheriting any garbage.
    """
    path = tmp_path / "journal.jsonl"
    script = tmp_path / "crash_writer.py"
    script.write_text(_CHILD_SCRIPT, encoding="utf-8")

    process = subprocess.Popen(
        [sys.executable, str(script), str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stdout.readline()
        assert line.strip() == "READY"
        time.sleep(0.2)
    finally:
        process.kill()
        process.wait(timeout=10)

    assert path.exists()
    journal = TransactionJournal(path)
    assert journal.records() == ()  # no valid records; partial tail discarded
    journal.append("stage", {"snapshot": "b" * 64})
    assert [r.event for r in journal.records()] == ["stage"]

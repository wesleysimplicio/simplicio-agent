#!/usr/bin/env python3
"""Deterministic issue-repro probe for honest backlog drains.

Extracts `simplicio ...` commands cited in GitHub issue bodies, runs each with a
hard timeout (Python subprocess — macOS has no `timeout` binary), and classifies:
  rc=0              -> OK (command works on current build)
  rc!=0 (no hang)   -> ERR (often incomplete usage in the issue body)
  timeout/hang      -> HANG (active bug — real work item)

Usage:
  export GH_REPO=wesleysimplicio/simplicio-runtime
  python3 issue_repro_probe.py --repo $GH_REPO --limit 2000 --timeout 60 --workers 16
  # writes repro_results.json: [{repo,number,cmd,sub,rc,dt,out,hang}]

This is the FIRST gate before any `gh issue close`. A clean repro is close-evidence
ONLY for a specific bug report whose exact failing command now works — never for an
epic/feature whose body merely mentions a working command.
"""

import argparse
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

CMD_RE = re.compile(
    r"`?(?P<cmd>simplicio\s+[a-z][\w-]*(?:\s+(?:--?[\w-]+|[^\s`]+))*)`?",
    re.I,
)
VALID_SUBS = {
    "doctor",
    "map",
    "runtime",
    "plan",
    "run",
    "validate",
    "edit",
    "shell",
    "memory",
    "savings",
    "agents",
    "issue-factory",
    "sprint",
    "workflow",
    "evidence",
    "status",
    "capabilities",
    "benchmark",
    "cron",
    "compact",
    "chat",
    "mapper",
    "dev-cli",
    "exec",
    "decide",
    "goal",
    "orientation",
    "trajectory",
    "task",
    "governor",
    "parallelism",
    "cache",
    "pr",
    "precedent",
    "issue-worktree",
    "cloud-watch",
    "contracts",
    "infra-advanced",
    "diagnostics",
    "update",
    "login",
    "auth",
    "license",
    "telegram",
    "discord",
    "browser",
    "computer-use",
    "model",
    "packages",
    "endpoint",
    "mcp",
    "meta",
    "symbol",
    "search",
    "recall",
    "skill",
    "skills",
    "learn",
    "propose",
    "apply",
    "gate",
    "nest",
    "claims",
    "wave",
}

DEFECT_LABELS = frozenset({"assert", "bug", "defect", "regression"})
VERDICTS = frozenset({"PASS", "FAIL", "UNVERIFIED"})
CLOSE_GATE_RECEIPT_SCHEMA = "simplicio-agent/issue-close-gate/v1"
_REPORT_MARKER_RE = re.compile(
    r"\b(?:actual|fail(?:ed|ing|ure)?|repro(?:duce|duction)?|reported)\b"
    r"|command\s+to\s+reproduce",
    re.I,
)


@dataclass(frozen=True)
class CloseGateDecision:
    """The probe's safe-to-close decision; denied decisions are quarantine receipts."""

    allowed: bool
    status: str
    reason: str
    verdict: str = "UNVERIFIED"

    def to_dict(self):
        return {
            "schema": CLOSE_GATE_RECEIPT_SCHEMA,
            "allowed": self.allowed,
            "status": self.status,
            "verdict": self.verdict,
            "reason": self.reason,
        }


def verify_close_gate_receipt(receipt):
    """Validate the shape and consistency of a serialized close-gate receipt."""

    if not isinstance(receipt, dict):
        return False
    if receipt.get("schema") != CLOSE_GATE_RECEIPT_SCHEMA:
        return False
    if not isinstance(receipt.get("allowed"), bool):
        return False
    if receipt.get("status") not in {"closeable", "quarantined"}:
        return False
    if receipt.get("verdict") not in VERDICTS:
        return False
    if not isinstance(receipt.get("reason"), str) or not receipt["reason"].strip():
        return False
    return receipt["allowed"] is (receipt["status"] == "closeable") and (
        receipt["allowed"] is (receipt["verdict"] == "PASS")
    )


def _receipt_verdict(value, label):
    """Return a receipt verdict, rejecting legacy truthy flags as unverified."""

    if not isinstance(value, dict):
        return "UNVERIFIED", f"{label} receipt is missing or malformed"
    verdict = value.get("status")
    if verdict not in VERDICTS:
        return "UNVERIFIED", f"{label} receipt status is unverified"
    reference = value.get("receipt")
    if not isinstance(reference, str) or not reference.strip():
        return "UNVERIFIED", f"{label} receipt reference is missing"
    return verdict, ""


def _label_names(issue):
    labels = issue.get("labels") or []
    names = set()
    for label in labels:
        name = label.get("name", "") if isinstance(label, dict) else str(label)
        if isinstance(name, str) and name.strip():
            names.add(name.strip().lower())
    return names


def has_defect_label(issue):
    """Return whether an issue has a concrete defect signal for closing."""

    return bool(_label_names(issue) & DEFECT_LABELS)


def extract_reported_cmds(body):
    """Extract commands explicitly tied to a reported failure or reproduction.

    ``extract_cmds`` intentionally finds every cited command for probing.  This
    narrower extractor is the close gate: an arbitrary command mentioned in an
    issue cannot stand in for the exact failing command.
    """

    lines = (body or "").splitlines()
    reported = []
    in_fence = False
    fence_is_report = False
    report_context = False
    for line in lines:
        if line.strip().startswith("```"):
            if not in_fence:
                fence_is_report = report_context
            in_fence = not in_fence
            if not in_fence:
                fence_is_report = False
            continue

        if _REPORT_MARKER_RE.search(line):
            report_context = True
        commands = extract_cmds(line)
        if commands and (report_context or (in_fence and fence_is_report)):
            reported.extend(commands)
        if not in_fence and not line.strip():
            report_context = False
    return tuple(dict.fromkeys(reported))


def evaluate_close_gate(issue, result, *, merged_pr=None, evidence=None):
    """Evaluate whether one probe result may support issue closure.

    The default is deliberately quarantine.  A passing command is insufficient
    without the issue's defect label, exact reported command, merged delivery,
    and independent evidence receipt.
    """

    def quarantine(reason, verdict="UNVERIFIED"):
        return CloseGateDecision(False, "quarantined", reason, verdict)

    if not has_defect_label(issue):
        return quarantine("missing defect label")
    command = (result.get("cmd") or "").strip()
    if command not in extract_reported_cmds(issue.get("body")):
        return quarantine("command is not the exact reported repro")
    if result.get("hang"):
        return quarantine("reported repro hangs", "FAIL")
    if result.get("hang") is not False:
        return quarantine("repro hang status is unverified")
    if not isinstance(result.get("rc"), int) or isinstance(result.get("rc"), bool):
        return quarantine("repro exit code is unverified")
    if result.get("rc") != 0:
        return quarantine("reported repro does not pass", "FAIL")
    delivery_verdict, delivery_reason = _receipt_verdict(
        merged_pr, "merged delivery"
    )
    if delivery_verdict != "PASS":
        return quarantine(delivery_reason, delivery_verdict)
    evidence_verdict, evidence_reason = _receipt_verdict(
        evidence, "independent evidence"
    )
    if evidence_verdict != "PASS":
        return quarantine(evidence_reason, evidence_verdict)
    return CloseGateDecision(
        True, "closeable", "all close-gate evidence is present", "PASS"
    )


def extract_cmds(body):
    if not body:
        return []
    out = []
    for m in CMD_RE.finditer(body or ""):
        c = m.group("cmd").strip().strip("`").strip().rstrip(".,;:")
        if len(c.split()) >= 2:
            out.append(c)
    return out


def is_exec(cmd):
    p = cmd.split()
    if len(p) < 2 or p[0] != "simplicio":
        return None
    if p[1] in ("runtime", "issue-factory", "issue-worktree"):
        sub = " ".join(p[1:3])
    else:
        sub = p[1]
    return sub if (sub in VALID_SUBS or sub.split()[0] in VALID_SUBS) else None


def run_one(cmd, timeout):
    t0 = time.time()
    try:
        r = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, timeout=timeout
        )
        return {
            "cmd": cmd,
            "rc": r.returncode,
            "dt": round(time.time() - t0, 1),
            "out": (r.stdout + r.stderr)[:200],
            "hang": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": cmd,
            "rc": 124,
            "dt": timeout,
            "out": "TIMEOUT/HANG",
            "hang": True,
        }
    except Exception as e:
        return {
            "cmd": cmd,
            "rc": -1,
            "dt": round(time.time() - t0, 1),
            "out": f"ERR {e}",
            "hang": False,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default="repro_results.json")
    a = ap.parse_args()

    raw = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "-R",
            a.repo,
            "-s",
            "open",
            "--limit",
            str(a.limit),
            "--json",
            "number,title,body,labels",
        ],
        capture_output=True,
        text=True,
    )
    issues = json.loads(raw.stdout)
    tasks = []
    seen = set()
    issue_by_number = {it["number"]: it for it in issues}
    for it in issues:
        for c in extract_cmds(it.get("body") or ""):
            sub = is_exec(c)
            if not sub:
                continue
            key = (it["number"], c)
            if key in seen:
                continue
            seen.add(key)
            tasks.append({
                "repo": a.repo.split("/")[-1],
                "number": it["number"],
                "cmd": c,
                "sub": sub,
            })
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, t["cmd"], a.timeout): t for t in tasks}
        for f in as_completed(futs):
            t = futs[f]
            r = f.result()
            results.append({
                **t,
                **r,
                "close_gate": evaluate_close_gate(
                    issue_by_number[t["number"]], r
                ).to_dict(),
            })
    with open(a.out, "w", encoding="utf-8") as output:
        json.dump(results, output, indent=0)
    hangs = [r for r in results if r["hang"]]
    errs = [r for r in results if r["rc"] not in (0,) and not r["hang"]]
    oks = [r for r in results if r["rc"] == 0]
    print(
        f"TOTAL={len(results)} OK={len(oks)} ERR={len(errs)} HANG={len(hangs)} -> {a.out}"
    )
    for r in hangs:
        print(f"  HANG {r['repo']}#{r['number']}: {r['cmd'][:60]}")


if __name__ == "__main__":
    main()

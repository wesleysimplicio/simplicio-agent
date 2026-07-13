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
import argparse, json, re, subprocess, time, os
from concurrent.futures import ThreadPoolExecutor, as_completed

CMD_RE = re.compile(r'`?(?:^|\s)(simplicio\s+[a-z][\w\-]*(?:\s+[a-z][\w\-]+)*(?:\s+--?[\w\-]+(?:\s+[^\s`]+)?)*)`?', re.I)
VALID_SUBS = {
    "doctor","map","runtime","plan","run","validate","edit","shell","memory","savings",
    "agents","issue-factory","sprint","workflow","evidence","status","capabilities","benchmark",
    "cron","compact","chat","mapper","dev-cli","exec","decide","goal","orientation","trajectory",
    "task","governor","parallelism","cache","pr","precedent","issue-worktree","cloud-watch",
    "contracts","infra-advanced","diagnostics","update","login","auth","license","telegram",
    "discord","browser","computer-use","model","packages","endpoint","mcp","meta","symbol",
    "search","recall","skill","skills","learn","propose","apply","gate","nest","claims","wave",
}

def extract_cmds(body):
    if not body:
        return []
    out = []
    for m in CMD_RE.finditer(body or ""):
        c = m.group(1).strip().strip("`").strip()
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
        r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=timeout)
        return {"cmd": cmd, "rc": r.returncode, "dt": round(time.time()-t0, 1),
                "out": (r.stdout + r.stderr)[:200], "hang": False}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "rc": 124, "dt": timeout, "out": "TIMEOUT/HANG", "hang": True}
    except Exception as e:
        return {"cmd": cmd, "rc": -1, "dt": round(time.time()-t0, 1), "out": f"ERR {e}", "hang": False}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default="repro_results.json")
    a = ap.parse_args()

    raw = subprocess.run(["gh", "issue", "list", "-R", a.repo, "-s", "open",
                          "--limit", str(a.limit),
                          "--json", "number,title,body,labels"],
                         capture_output=True, text=True)
    issues = json.loads(raw.stdout)
    tasks = []
    seen = set()
    for it in issues:
        for c in extract_cmds(it.get("body") or ""):
            sub = is_exec(c)
            if not sub:
                continue
            key = (it["number"], c)
            if key in seen:
                continue
            seen.add(key)
            tasks.append({"repo": a.repo.split("/")[-1], "number": it["number"],
                          "cmd": c, "sub": sub})
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, t["cmd"], a.timeout): t for t in tasks}
        for f in as_completed(futs):
            t = futs[f]
            r = f.result()
            results.append({**t, **r})
    json.dump(results, open(a.out, "w"), indent=0)
    hangs = [r for r in results if r["hang"]]
    errs = [r for r in results if r["rc"] not in (0,) and not r["hang"]]
    oks = [r for r in results if r["rc"] == 0]
    print(f"TOTAL={len(results)} OK={len(oks)} ERR={len(errs)} HANG={len(hangs)} -> {a.out}")
    for r in hangs:
        print(f"  HANG {r['repo']}#{r['number']}: {r['cmd'][:60]}")

if __name__ == "__main__":
    main()

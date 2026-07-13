# Issue triage under scope freeze

Use when the user asks for a force-tarefa over many GitHub issues in `simplicio-runtime` or a similarly large repo.

## Fast triage loop
1. Enumerate the live queue from GitHub directly:
   ```bash
   gh issue list --state open --limit 100 --json number,title,labels,body
   ```
2. Cluster issues by theme before deciding any edits.
3. Separate each issue into one of four buckets:
   - **in-scope fix now**
   - **small verifiable fix**
   - **duplicate of canonical issue**
   - **out of scope / not planned under freeze**
4. Close only after classification is explicit.

## Duplicate handling
- Prefer the **lower-numbered issue** as canonical unless the body clearly says otherwise.
- Close duplicates with `--reason duplicate` and point to the canonical issue in the comment/body.
- Re-run `gh issue list --state open ...` after a batch close to verify the set actually shrank.

Example:
```bash
gh issue close 2843 --reason duplicate --duplicate-of 2840 -c 'Duplicate of #2840: same benchmark target/title; keeping the lower-number issue as canonical.'
```

## Scope-freeze handling
- For product/agent-parity work that is outside the current runtime freeze, close with `--reason not planned`.
- Keep the comment short and concrete: mention the freeze and the target repo/surface that should own it.
- Do not spin a long debate in the issue body; leave a one-line routing note.

Example:
```bash
gh issue close 2963 --reason 'not planned' -c 'Kernel-only scope freeze: this belongs in simplicio-agent or a product-facing fork, not in simplicio-runtime.'
```

## Verification
- After any bulk close, re-run the issue list and confirm the intended issues are absent from the open queue.
- If the open queue still includes a supposed duplicate or out-of-scope item, do not assume the close failed silently — inspect that issue directly.

## Practical note
- Keep the work split into thematic clusters and parallelize the inspection.
- Use the GitHub CLI for live ground truth instead of relying on preserved task lists or compacted chat state.

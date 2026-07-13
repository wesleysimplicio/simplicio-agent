# External code absorption via parallel agents

**When to use:** The user identifies an external GitHub profile/project (e.g. "absorva o melhor do Jesse") and wants you to port concepts, patterns, or code into your own repos. NOT for evaluating a single PR or a one-file snippet — use normal review/port for that.

## Protocol

### Phase 1 — Reconnaissance (read, don't guess)

1. **Browse the profile.** Navigate to `https://github.com/<user>` — note the repo count, descriptions, languages.
2. **Identify relevant repos** by name and description. Filter out forks, mirrors, archives.
3. **Read each relevant README** — from raw URL for speed: `https://raw.githubusercontent.com/<user>/<repo>/main/README.md`
4. **Read key source files** — the actual implementation. For core algorithms/frameworks, read:
   - Entry point / main module
   - Verification/test files (these show the ACTUAL contract, not just the README claim)
   - CLI / API surface
5. **Classify each repo's value:**
   - 🏆 **Altíssimo** — directly applicable, fills a gap we have, novel approach
   - ⚡ **Alto/médio** — useful concept, needs adaptation
   - 🔄 **Já refletido** — we already have something similar
   - ❌ **Não aplicável** — too specific to their stack

### Phase 2 — Map to target repos

Create a task × target matrix. Each row = one feature/concept to absorb. Each column = one target repo.

| Concept | Target repo | What to create | Why it fits |
|---|---|---|---|
| N-Nest gate | simplicio-runtime | New crate `simplicio-gate` | Native Rust implementation of corrective gate |
| Brown-Hilbert | simplicio-runtime | New crate `simplicio-addressing` | port.port.port addressing for agent tree |
| Harness-edit | simplicio-dev-cli | `score-skill` command | CLI command for skill scoring |
| ... | ... | ... | ... |

### Phase 3 — Dispatch parallel implementation agents

**Context is CRITICAL** — each subagent needs:
1. The EXACT source code from the external repo (copy key functions verbatim into the task context)
2. The exact target repo path
3. Which existing files to modify (or new files to create)
4. The specific target pattern (GitHub repo, path, file path)

**Do NOT** ask the subagent to re-read the external repo — include the source code directly in the `context` field. The raw content is already in your context from Phase 1 — pass it through.

**Commit message formula (Conventional Commits):**
```
feat(<scope>): absorb <external_project> <concept> — <one-line description>
```

### Phase 4 — Post-absorption verification

After all subagents complete:
1. Check `git status --short` on each target repo
2. For Rust repos: run `cargo check` to catch compilation conflicts from concurrent edits
3. For Python repos: run basic import/syntax check
4. Commit & push each repo (or handle as batch — see `multi-repo-batch-git.md`)

### Design decisions

| Question | Default | Rationale |
|---|---|---|
| New crate or extend existing? | **New crate** when concept is standalone (gate, addressing, claims); **extend existing** when it adds a module (fabric bus → agents, seed identity → agents) | Cleaner separation, easier to review, independent versioning |
| Rust port or Python wrapper? | **Native Rust port** for performance crates; **Python CLI** for dev-tool commands | Fits the target repo's language |
| Include tests? | **Yes** — port the verification files too (depth-N, scenario checks) | The verification IS the proof the concept works |
| Copy verbatim or adapt? | **Adapt** — rename types, use target repo's conventions, integrate with existing patterns | The concept is valuable, not the exact variable names |
| Document the source? | **Yes** — include a comment like `// Absorbed from JesseBrown1980/N-Nest-Prime` in module-level docs | Attribution + traceability |

### Pitfalls

- **Don't guess the code** — if you didn't read the source file, you can't absorb it. Read at least the README and one key implementation file before dispatching.
- **Sub-projects within a repo** — the external repo may be a monorepo with multiple packages. Read the directory structure first to find what you need.
- **Missing `main` branch** — external repos may use `master` as default. Check the branch name in the URL (raw.githubusercontent.com uses branch in the path).
- **Generated/config files** — skip `.hbp`, `.sha256`, `.ps1` (unless relevant), and personal config files. Absorb ALGORITHMS, not deployment scripts.
- **Context fit** — don't absorb something that already exists in your target. Check `search_files` in target repo for similar patterns first.
- **Language mismatch** — if source is JS but target is Rust, you're porting the ALGORITHM, not transliterating. Explain the concept in the task context so the agent can re-implement idiomatically.
- **User language** — final report and status updates in user's language (pt-BR, en, etc.). Code in English.

# gh CLI PR Query Patterns — Field Availability & Quirks

> Reference for querying PRs on NousResearch/hermes-agent (and any GitHub repo).
> Validated against `gh` v2.x and GitHub REST API v3.

## gh search prs — JSON Field Availability

```bash
# Available fields (from --json help):
#   assignees, author, authorAssociation, body, closedAt, commentsCount,
#   createdAt, id, isDraft, isLocked, isPullRequest, labels, number,
#   repository, state, title, updatedAt, url

# ❌ NOT available: headRefName, baseRefName, mergedAt, mergeable, reviews
```

### Quirk: merged queries

```bash
# ❌ DOES NOT WORK — invalid value "merged" for --state
gh search prs --state merged ...

# ✅ CORRECT — use --merged flag with --state closed
gh search prs --state closed --merged --json number --jq 'length'

# ✅ CORRECT — or use REST API (more fields)
gh api "search/issues?q=is:pr+repo:.../...-author:...-is:merged" \
  --jq '.items[] | [.number,.title,.pull_request.merged_at] | @tsv'
```

### Quirk: merged_at not in gh search prs output

The `--json` output does NOT include `mergedAt` or `merged_at`.
To get merge timestamp AND merged_by:

```bash
# Use REST API — pull_request.merged_at IS available here
gh api "search/issues?q=is:pr+repo:NousResearch/hermes-agent+author:wesleysimplicio+is:merged&sort=created&order=desc&per_page=5" \
  --jq '.items[] | {number: .number, title: .title, merged_at: .pull_request.merged_at, merged_by: .merged_by}'
```

## Common Query Patterns

### 1. Count open PRs by author

```bash
gh search prs --repo NousResearch/hermes-agent \
  --author wesleysimplicio \
  --state open \
  --json number --jq 'length'
```

### 2. List open PRs with labels and draft status

```bash
gh search prs --repo NousResearch/hermes-agent \
  --author wesleysimplicio \
  --state open \
  --json number,title,createdAt,labels,isDraft \
  --jq '.[] | [.number,.title,.createdAt,.isDraft] | @tsv' \
  | sort -t$'\t' -k1 -n
```

### 3. Label breakdown of open PRs

```bash
gh search prs --repo NousResearch/hermes-agent \
  --author wesleysimplicio \
  --state open \
  --json number,title,labels,isDraft \
  --jq '[.[] | {num: .number, labels: [.labels[].name]}] | sort_by(.num)'
```

### 4. Count merged PRs (all time)

```bash
gh search prs --repo NousResearch/hermes-agent \
  --author wesleysimplicio \
  --state closed --merged \
  --json number --jq 'length'
```

### 5. Merged PR details (with timestamps)

```bash
gh api "search/issues?q=is:pr+repo:NousResearch/hermes-agent+author:wesleysimplicio+is:merged&sort=created&order=desc&per_page=5" \
  --jq '.items[] | [.number,.title,.pull_request.merged_at] | @tsv'
```

### 6. Check for draft vs non-draft

```bash
gh search prs --repo NousResearch/hermes-agent \
  --author wesleysimplicio \
  --state open \
  --json isDraft --jq '[group_by(.isDraft)[] | {draft: .[0].isDraft, count: length}]'
```

### 7. Count closed (non-merged) PRs

```bash
# Total closed
TOTAL=$(gh search prs --repo NousResearch/hermes-agent \
  --author wesleysimplicio \
  --state closed --json number --jq 'length')
# Merged only
MERGED=$(gh search prs --repo NousResearch/hermes-agent \
  --author wesleysimplicio \
  --state closed --merged --json number --jq 'length')
# Closed without merge
echo $((TOTAL - MERGED))
```

### 8. Most recent creation timestamps

Useful to confirm when PRs were pushed:

```bash
gh search prs --repo NousResearch/hermes-agent \
  --author wesleysimplicio \
  --state open \
  --json number,createdAt \
  --jq '[.[].createdAt] | unique | sort'
```

## Key Takeaways

| You try this | It fails | Use this instead |
|---|---|---|
| `--state merged` | invalid value | `--state closed --merged` |
| `--json headRefName` | unknown field | `--json createdAt` (headRefName not in search endpoint) |
| `--json mergedAt` | unknown field | REST API `.pull_request.merged_at` |
| `--json reviews` | unknown field | REST API `/pulls/N/reviews` |

## REST API vs gh CLI — When to Use Each

| Query | gh CLI | REST API |
|---|---|---|
| Count open PRs | ✅ `gh search prs --state open` | Overkill |
| List PRs with labels | ✅ `--json labels` | Equivalent |
| Merged PRs with timestamp | ❌ no `mergedAt` field | ✅ `search/issues?q=is:merged` + `.pull_request.merged_at` |
| Merged by user | ❌ not available | ✅ `.merged_by.login` |
| Review status | ❌ not in search | ✅ `/pulls/N/reviews` or `/pulls/N` |

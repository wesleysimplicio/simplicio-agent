# Simplicio-Tasks Loop: 100 PRs — Armed

iteration: 1
max_iterations: 10
completion_promise: "SIMPLICIO_DONE"
evidence_required: true

GOAL: Create 100 PRs across simplicio ecosystems with near-0 tokens
  - Split existing big PRs into directory-level PRs
  - Apply validated patterns across 5+ repos
  - Each PR: 1 directory × 1 pattern = clean, focused, mergeable
  - Total: 100 PRs minimum

CURRENT STATE:
  - 11 PRs open (10 Hermes + 1 Simplicio Runtime)
  - 53 opportunities found across 5 simplicio repos
  - 6 agents dispatched but results pending
  - Cron 1min active for monitoring

STRATEGY:
  1. SPLIT: Take existing big PRs (#58918 f-strings, #58909 imports) → 6+5 = 11 new PRs
  2. APPLY: Deploy 6 agents × 5 repos × 2 patterns = 30+ PRs
  3. NEW: Find additional patterns (dead code, type hints) = 20+ PRs
  4. EXTERNAL: NousResearch repos, JesseBrown1980 repos = 30+ PRs
  Total potential: 11 + 30 + 20 + 30 = ~91 + 9 existing = 100

NEXT WAVE:
  Split #58918 (f-strings, 22 files) by directory:
  - tools/ → 1 PR (5 files, browser, tts, discord, camofox, image_gen)
  - agent/ → 1 PR (5 files, conversation_loop, curator, moa_loop, oneshot, chat_completion)
  - hermes_cli/ → 1 PR (3 files)
  - plugins/ → 1 PR (2 files)
  - gateway/ → 1 PR (2 files)
  - cron+scripts+state/ → 1 PR (3 files)
  = 6 PRs

  Split #58909 (unused imports, 18 files) by directory:
  - agent/ → 1 PR (2 files)
  - gateway/ → 1 PR (3 files)
  - hermes_cli/ → 1 PR (6 files)
  - plugins/ → 1 PR (3 files)
  - tools/ → 1 PR (3 files)
  = 5 PRs

  TOTAL FROM SPLITS: 11 NEW PRs

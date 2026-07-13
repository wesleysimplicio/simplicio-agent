# Snake benchmark fixture

Self-contained, playable Snake browser fixture used by the runtime
performance harness (issue #266). Everything needed to run it lives in this
directory — no build step, no framework, a single `index.html`.

## What it is

- `index.html` — the game. Name prompt before gameplay, keyboard (arrow keys
  + WASD) and touch (on-screen buttons + canvas swipe) controls, real
  wall/self collision detection, score calculation, restart, and a
  persistent top-10 scoreboard stored in `localStorage`
  (`simplicio_snake_scoreboard_v1`), bounded and sorted by score descending.
- `e2e/snake.spec.ts` — Playwright E2E proving the prompt, gameplay,
  finish/game-over, restart, and scoreboard persistence/ordering/cap-at-10.
- `scripts/serve.mjs` — zero-dependency static file server (Playwright's
  `webServer` launches it automatically).
- `scripts/artifact-reporter.mjs` — custom Playwright reporter that emits
  `artifacts/snake_benchmark_result.json`, schema
  `simplicio.snake-benchmark-fixture/v1`, mapping each acceptance-criterion
  bucket (`name_prompt`, `controls`, `finish`, `restart`,
  `persistence_ordering_cap`) to pass/fail + duration, for the runtime
  performance harness to consume.

## Run it (one command, clean checkout)

```bash
cd benchmarks/snake_fixture
npm install
npx playwright install --with-deps chromium   # first run only
npm test
```

This runs the full E2E suite headless against a local static server and
writes `artifacts/snake_benchmark_result.json`.

To eyeball the game in a real browser instead of running the suite:

```bash
npm run serve
# open http://localhost:4173/index.html
```

## Test-only determinism seam

`index.html` supports three URL query params, all off by default in a
normal run:

- `?fast=1` — shortens the game tick interval, for quick automated runs.
- `?seed=<n>` — seeds the food-placement RNG (mulberry32) for reproducible
  runs, which the perf harness needs when comparing engines/agents on the
  same task.
- `?testSeam=1` — **test-only**. Food always spawns one cell ahead of the
  snake's head, so an automated test can score points deterministically
  instead of depending on random food placement. It does not change
  collision, scoring, or persistence logic. One E2E test (`collision ends
  the game…`) deliberately runs *without* this seam to exercise unmodified
  gameplay end-to-end.

## Runtime integration

This fixture is meant to be consumable by `simplicio-runtime` issue #3161
and the existing perf/token issues (#23, #111, #116, #119, #136, #157) in
that repo — the `artifacts/snake_benchmark_result.json` output is the
integration point. Wiring it into that repo's harness, and running the
actual comparative Hermes-control benchmark required before any speed/token
claim, is out of scope for this PR (different repo, different session) and
is called out explicitly rather than faked here.

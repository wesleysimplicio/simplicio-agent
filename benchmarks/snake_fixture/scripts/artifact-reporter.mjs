// Custom Playwright reporter: translates the raw test results into the
// machine-readable artifact the runtime performance harness consumes.
// Schema follows this repo's `simplicio.<name>/v1` convention (see
// scripts/bench_token_estimators.py, tools/perf_gate/compare.py, etc. in
// the repo root for prior art).
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const CRITERIA = [
  { key: "name_prompt", match: /prompts for player name/i },
  { key: "controls", match: /(keyboard controls|touch controls)/i },
  { key: "finish", match: /collision ends the game/i },
  { key: "restart", match: /restart resets/i },
  { key: "persistence_ordering_cap", match: /scoreboard persists/i },
];

export default class SimplicioArtifactReporter {
  constructor(options = {}) {
    this.outputFile = options.outputFile || "artifacts/snake_benchmark_result.json";
    this.tests = [];
  }

  onTestEnd(test, result) {
    this.tests.push({
      title: test.title,
      status: result.status,
      duration_ms: result.duration,
    });
  }

  onEnd(result) {
    const criteria = {};
    for (const c of CRITERIA) {
      const matched = this.tests.filter((t) => c.match.test(t.title));
      const status = matched.length === 0
        ? "not_run"
        : matched.every((t) => t.status === "passed")
          ? "pass"
          : "fail";
      criteria[c.key] = {
        status,
        tests: matched.map((t) => t.title),
        duration_ms: matched.reduce((sum, t) => sum + t.duration_ms, 0),
      };
    }

    const totals = this.tests.reduce(
      (acc, t) => {
        acc[t.status] = (acc[t.status] || 0) + 1;
        acc.total += 1;
        return acc;
      },
      { total: 0 }
    );

    const artifact = {
      schema: "simplicio.snake-benchmark-fixture/v1",
      fixture: "snake",
      generated_at: new Date().toISOString(),
      overall_status: result.status,
      totals,
      criteria,
      tests: this.tests,
    };

    const outPath = path.resolve(this.outputFile);
    mkdirSync(path.dirname(outPath), { recursive: true });
    writeFileSync(outPath, JSON.stringify(artifact, null, 2) + "\n");
    console.log(`\nsimplicio.snake-benchmark-fixture/v1 artifact written to ${outPath}`);
  }
}

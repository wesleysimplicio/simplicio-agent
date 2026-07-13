import { test, expect } from "@playwright/test";

/**
 * E2E proof for the Snake benchmark fixture (issue #266). Covers, in one
 * suite: the name prompt, real keyboard/touch-driven gameplay, the
 * game-over/finish state, restart, and the persistent bounded/ordered
 * top-10 scoreboard (persistence + ordering + cap-at-10).
 *
 * `?testSeam=1` is a documented, test-only determinism seam (see
 * index.html) that makes food spawn directly ahead of the snake so score
 * accrual is deterministic instead of depending on random food placement.
 * The finish/game-over test intentionally runs WITHOUT the seam, driving a
 * real wall collision, so at least one test exercises unmodified gameplay.
 */

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await page.evaluate(() => window.localStorage.clear());
});

test("prompts for player name before gameplay starts", async ({ page }) => {
  await page.goto("/index.html");
  await expect(page.getByTestId("name-screen")).toBeVisible();
  await expect(page.getByTestId("game-screen")).toBeHidden();

  await page.getByTestId("name-input").fill("Ada");
  await page.getByTestId("start-button").click();

  await expect(page.getByTestId("game-screen")).toBeVisible();
  await expect(page.getByTestId("name-screen")).toBeHidden();
  await expect(page.getByTestId("active-player-name")).toHaveText("Ada");
  expect(await page.evaluate(() => window.__snake.getPlayerName())).toBe("Ada");
});

test("keyboard controls move the snake and score increases", async ({ page }) => {
  await page.goto("/index.html?fast=1&testSeam=1&seed=7");
  await page.getByTestId("name-input").fill("Grace");
  await page.getByTestId("start-button").click();

  // Food always spawns one cell ahead under the test seam, so repeated
  // forward presses reliably score points.
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(60);
  }

  const score = await page.evaluate(() => window.__snake.getScore());
  expect(score).toBeGreaterThan(0);
  await expect(page.getByTestId("score")).not.toHaveText("0");
});

test("touch controls move the snake and score increases", async ({ page }) => {
  await page.goto("/index.html?fast=1&testSeam=1&seed=11");
  await page.getByTestId("name-input").fill("Touchy");
  await page.getByTestId("start-button").click();

  await page.getByTestId("touch-down").click();
  await page.waitForTimeout(80);
  await page.getByTestId("touch-right").click();
  await page.waitForTimeout(80);
  await page.getByTestId("touch-down").click();
  await page.waitForTimeout(150);

  const score = await page.evaluate(() => window.__snake.getScore());
  expect(score).toBeGreaterThan(0);
});

test("collision ends the game with a game-over overlay and records the score", async ({ page }) => {
  await page.goto("/index.html?fast=1&seed=3");
  await page.getByTestId("name-input").fill("Wallhugger");
  await page.getByTestId("start-button").click();

  // Real (non-seam) gameplay: drive straight into the right wall.
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("gameover-screen")).toBeVisible({ timeout: 15_000 });

  const finalScoreText = await page.getByTestId("final-score").textContent();
  expect(finalScoreText).not.toBeNull();
  expect(Number(finalScoreText)).toBeGreaterThanOrEqual(0);

  const scoreboard = await page.evaluate(() => window.__snake.getScoreboard());
  expect(scoreboard.some((e: { name: string }) => e.name === "Wallhugger")).toBe(true);
});

test("restart resets the round and keeps the player name without re-prompting", async ({ page }) => {
  await page.goto("/index.html?fast=1&seed=5");
  await page.getByTestId("name-input").fill("Restarter");
  await page.getByTestId("start-button").click();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("gameover-screen")).toBeVisible({ timeout: 15_000 });

  await page.getByTestId("restart-button").click();

  await expect(page.getByTestId("game-screen")).toBeVisible();
  await expect(page.getByTestId("name-screen")).toBeHidden();
  await expect(page.getByTestId("score")).toHaveText("0");
  expect(await page.evaluate(() => window.__snake.getPlayerName())).toBe("Restarter");
});

test("scoreboard persists top-10 entries across reload with correct ordering and a cap at 10", async ({ page }) => {
  await page.goto("/index.html");

  // Seed 12 finished rounds directly through the same recordScore()
  // function the real game-over path calls, to exercise persistence,
  // ordering, and the cap deterministically without playing 12 rounds.
  await page.evaluate(() => {
    for (let i = 1; i <= 12; i++) {
      window.__snake.recordScore(`Player${i}`, i * 10);
    }
  });

  await page.reload();

  const scoreboard = await page.evaluate(() => window.__snake.getScoreboard());
  expect(scoreboard).toHaveLength(10);

  const scores = scoreboard.map((e: { score: number }) => e.score);
  const sortedDesc = [...scores].sort((a, b) => b - a);
  expect(scores).toEqual(sortedDesc);
  expect(scores[0]).toBe(120);
  expect(scores).not.toContain(10); // lowest two entries were evicted by the cap
  expect(scores).not.toContain(20);

  const listItems = await page.getByTestId("scoreboard-list-home").locator("li").allTextContents();
  expect(listItems).toHaveLength(10);
  expect(listItems[0]).toContain("Player12");
  expect(listItems[0]).toContain("120");
});

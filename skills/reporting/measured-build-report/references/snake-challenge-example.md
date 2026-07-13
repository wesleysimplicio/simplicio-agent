# Worked example — Snake game build report (session 2026-07-08)

Challenge: "write a snake game using html, css and js. Ask name on begin, game
(modern), finished, store the ScoreBoard with top 10, open" + follow-up:
"preciso da medicao de metricas e gerar um html desse relatorio de passo a
passo".

## Deliverable
- `/Users/wesleysimplicio/snake-game.html` (opened in browser)

## Measured metrics (real, via measure_html.py + corrections)
- bytes: 13,729
- lines: 330
- words: 1,189
- html_parse_errors: [] (0)
- unclosed_tags: [] (0)
- css_rules_approx: 39
- css_vars: 8
- js_functions_approx: 21
- event_listeners: 6
- canvas_count: 1
- grid: GRID=24, SIZE=480 -> cells_per_side = 20
- measure time: ~1.4ms

## Requirement coverage (by token presence)
- Ask name on begin: nameInput + startScreen -> true
- Modern game: backdrop-filter + linear-gradient -> true
- Finished: gameOver() + overScreen -> true
- ScoreBoard top 10: maxPlayers=10 + slice(0, maxPlayers) -> true
- Persistent storage: localStorage key snakeScoreboard.v1 -> true
- Open in browser: `open` executed -> true
- Bonus pause (Space): e.key === ' ' -> true
- Bonus touch/swipe: touchstart/touchmove -> true
- Bonus sound + speed ramp: AudioContext + stepMs -> true

## Correction made during measurement (lesson)
First pass reported `cells_per_side: null` and `Pause support: false`
because the probe guessed the word "Space" and a fixed CELLS regex. Fixed by
computing cells = SIZE//GRID and detecting pause via `e.key === ' '`. Always
compute derived values; never guess.

## Report artifact
- `/Users/wesleysimplicio/snake-report.html` (opened) — neon dashboard with
  stat grid, coverage table, 7-step narrative, MEASURED| footer.

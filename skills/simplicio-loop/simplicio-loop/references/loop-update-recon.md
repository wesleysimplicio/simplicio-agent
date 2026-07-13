# Loop update recon

Session note: the latest `simplicio-loop` update was easiest to spot by checking the installed skill corpus and the runtime-linked docs together, not just repo docs.

## Propagation targets to keep in sync
- `simplicio-loop/SKILL.md`: mandatory execution engine, evidence-gated exits, `max_iterations` / budget ceiling, hook-driven and self-paced parity.
- `simplicio-runtime-packs/SKILL.md`: loop inversion rule (`simplicio-loop` is mandatory in runtime).
- `hermes-simplicio-hybrid/references/simplicio-loop-evolution.md`: HRM planner before watcher gate; flat fail-open if the planner is absent.
- `hermes-simplicio-hybrid/references/global-skills-simplicio-loop.md`: global install paths and hook inventory.

## Sync rule
If repo docs and installed skills disagree, treat that as doc drift and update both sides rather than one side only.
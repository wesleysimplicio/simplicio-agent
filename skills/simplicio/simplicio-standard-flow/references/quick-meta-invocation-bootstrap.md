# Quick meta invocations must stay cheap

## Lesson
If the CLI has top-level meta commands like `--help`, `-h`, `--version`, `-V`, or bare aliases like `help`/`version`, resolve them **before** any heavy boot work.

## Why
A heavy startup path can make tiny introspection commands fail or get killed before they print anything useful.

## Pattern
1. Parse the raw argv first.
2. Detect quick meta invocations.
3. Return help/version immediately.
4. Only then run startup hooks such as:
   - skill discovery
   - onboarding wizards
   - staged-update hooks
   - chat/TUI boot
   - provider/model initialization

## Verification
Smoke the cheap path directly:
- `simplicio --help`
- `simplicio -h`
- `simplicio --version`
- `simplicio -V`

These commands should complete without triggering the full runtime boot path.

## Related pitfall
If a meta command is unexpectedly slow or gets killed, check whether startup side effects were placed before the quick-path return rather than assuming the binary itself is broken.

# macOS tempdir vs sensitive-path guards

Use when a repo bug or test failure says a temp workspace under `/private/var/folders/...` is a sensitive system path.

## Pattern
- On macOS, `tempfile.gettempdir()` often resolves under `/private/var/folders/...`.
- Pytest `tmp_path` and other temp-workspace fixtures commonly live there too.
- A broad write guard that blocks all `/private/var/...` paths can accidentally reject legitimate temp workspaces.

## Durable fix
1. Resolve the candidate path and the real `tempfile.gettempdir()` root.
2. Treat the resolved temp root as an explicit safe exception.
3. Keep the broader `/private/var/...` guard for non-temp paths.
4. Add a regression test that uses the real temp root instead of assuming `/tmp`.

## Why this matters
Without the exception, validation can fail before the intended repo behavior is exercised, hiding the true contract behind a platform-specific path misclassification.

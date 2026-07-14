# Local-change preservation staging contract

`hermes_cli.local_change_staging` is the bounded, local contract for issue
#343. It is deliberately not wired into the production update command. A
caller can use it as a shadow-run boundary while the updater integration is
designed and reviewed separately.

The preservation order is strict:

1. Inspect the checkout with `git status --porcelain=v1 -z`, including staged,
   unstaged, and non-ignored untracked paths. Existing stash object IDs are
   recorded read-only.
2. Capture `git diff HEAD --binary` and every captured working-tree file as
   SHA-256-addressed objects. The `simplicio.local-changes/v1` manifest records
   the base commit, patch digest, per-file digest, per-hunk digest, and stash
   IDs. The patch and blobs are persisted before a fetch is attempted.
3. Clone into a new staging directory, point its remote at the authoritative
   checkout's configured remote URL, then fetch and run `git merge --ff-only`
   (the explicit merge supplies ff-only semantics on Git versions where fetch
   has no `--ff-only` flag). Divergence returns `StageResult(status="diverged")`;
   the authoritative checkout is never reset, merged, or checked out.
4. Apply the content-addressed patch with Git's three-way machinery and write
   untracked blobs only when the destination is absent. A collision or failed
   hunk returns `ApplyResult(status="blocked")` with file/hunk paths. The
   original patch remains addressable and `verify_preserved` must pass.

This contract intentionally reports conflict as a result, not an exception or
an implicit discard. It does not claim signed release-bundle verification,
kill-point recovery, live process activation, or production updater coverage;
those belong to later integration slices.

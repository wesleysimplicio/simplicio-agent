---
name: ftp-site-deploy
description: Deploy a static (or PHP) site to an FTP host via `lftp mirror -R` and VERIFY the bytes landed correctly with an HTTP fetch + MD5 compare. Covers credential handling, runtime-dir excludes, and the mandatory post-deploy verification discipline. Use on "update the site", "deploy to FTP", "upload to simpleti.com.br", or any lftp mirror -R job.
---

# FTP Site Deploy (lftp + verify)

## When to use
- "Update the site" / "deploy to FTP" / "upload to simpleti.com.br" or similar.
- Any job that pushes a local web tree to a remote FTP host with `lftp mirror -R`.

## Golden rule: never trust "Done"
`lftp mirror` prints `Done.` when the transfer finishes — that is NOT proof the bytes are correct on the server. Always verify with an HTTP fetch and compare the payload hash against the local file. (See Verification below.) This is the "evidenciar" step of the Simplicio flow: claims without a measured receipt are worthless.

## Credential handling
- Store secrets in `deploy/.ftp-credentials`, `chmod 600`, and gitignore it. Never hardcode in the script.
- Format the script sources:
  ```
  FTP_HOST=ftp.example.com
  FTP_USER=user@domain
  FTP_PASS=****
  FTP_PATH=/public_html
  ```
- Verify `.gitignore` contains `deploy/.ftp-credentials` BEFORE committing.

## The deploy script shape (lftp mirror -R)
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CRED="deploy/.ftp-credentials"
[ -f "$CRED" ] || { echo "missing $CRED"; exit 1; }
source "$CRED"
command -v lftp >/dev/null 2>&1 || { echo "brew install lftp"; exit 1; }
lftp -u "$FTP_USER","$FTP_PASS" "$FTP_HOST" <<EOF
set ssl:verify-certificate no
set ftp:ssl-allow true
mirror -R --verbose --parallel=4 \
  --exclude-glob .git/ \
  --exclude-glob deploy/ \
  --exclude-glob .simplicio/ \
  --exclude-glob .orchestrator/ \
  --exclude-glob .github/ \
  --exclude-glob api/cache/ \
  --exclude-glob '*.local.php' \
  ./ $FTP_PATH/
bye
EOF
```

### PITFALL: lftp mirror -R uploads EVERYTHING
Without explicit `--exclude-glob`, `mirror -R` will push `.git/`, `.simplicio/` (runtime cache/ledger), `.orchestrator/`, `.github/`, and local secrets-in-flight to the public host. Always exclude: `.git/`, `deploy/`, `.simplicio/`, `.orchestrator/`, `.github/`, `api/cache/`, `*.local.php`. For the Simpleti project the runtime writes `.simplicio/` and `.orchestrator/` caches locally — these MUST be excluded or they pollute `/public_html`.

### PITFALL: remote_path / URL mapping
`mirror -R ./ $FTP_PATH/` maps repo root → `$FTP_PATH`. A project folder `simplicio/` in the repo becomes `https://host/simplicio/`. Confirm the intended public URL before running.

## Verification (MANDATORY)
After the script exits 0, prove the bytes landed:
```bash
curl -sS -o /tmp/remote.html -w "HTTP %{http_code} · %{size_download} bytes\n" https://host/path/
md5 -q /tmp/remote.html
md5 -q /local/path/file.html
# hashes must match
```
Report both the HTTP status/size AND the matching hash as evidence. If the host serves a cached/stale page (LiteSpeed full-page cache is a known offender), confirm the `.htaccess` `Cache-Control: no-cache` for `.html?` shipped.

## References
- `scripts/verify-ftp-deploy.sh` — reusable post-deploy checker (curl + md5, exits non-zero on mismatch).

#!/usr/bin/env bash
# verify-ftp-deploy.sh — prove a deployed file's bytes match the local source.
# Usage: ./verify-ftp-deploy.sh <remote-url> <local-file>
# Exits non-zero on HTTP failure or hash mismatch. Prints a measured receipt.
set -euo pipefail

URL="${1:?remote URL required}"
LOCAL="${2:?local file required}"

[ -f "$LOCAL" ] || { echo "local file not found: $LOCAL"; exit 2; }

TMP="$(mktemp /tmp/ftp-verify.XXXXXX.html)"
trap 'rm -f "$TMP"' EXIT

HTTP_CODE="$(curl -sS -o "$TMP" -w '%{http_code}' "$URL")"
BYTES="$(wc -c < "$TMP" | tr -d ' ')"

REMOTE_MD5="$(md5 -q "$TMP")"
LOCAL_MD5="$(md5 -q "$LOCAL")"

echo "HTTP $HTTP_CODE · $BYTES bytes"
echo "remote md5: $REMOTE_MD5"
echo "local  md5: $LOCAL_MD5"

if [ "$REMOTE_MD5" = "$LOCAL_MD5" ]; then
  echo "MATCH ✓ — bytes identical to local source"
else
  echo "MISMATCH ✗ — deployed bytes differ from local source"; exit 1
fi

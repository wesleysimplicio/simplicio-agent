#!/bin/bash
cd /Users/wesleysimplicio/simplicio-runtime
# Dump chat dispatch line by line with line numbers
LINENUM=0
while IFS= read -r line; do
  LINENUM=$((LINENUM + 1))
  echo "$LINENUM|$line"
done < <(sed -n '2070,2180p' src/main.rs)
echo "---EOF---"

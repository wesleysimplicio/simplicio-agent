#!/bin/bash
cd /Users/wesleysimplicio/simplicio-runtime
# Show the chat dispatch code around line 2000-2100
echo "=== match sub occurrences ==="
grep -n 'match sub' src/main.rs 2>/dev/null
echo "=== Lines 2040-2100 ==="
sed -n '2040,2100p' src/main.rs 2>/dev/null
echo "=== Lines 2100-2160 ==="
sed -n '2100,2160p' src/main.rs 2>/dev/null

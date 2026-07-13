#!/bin/bash
cd /Users/wesleysimplicio/simplicio-runtime
OUTFILE=/tmp/chat-dispatch-output.txt
echo "=== match sub occurrences ===" > "$OUTFILE"
grep -n 'match sub' src/main.rs >> "$OUTFILE" 2>/dev/null
echo "=== Lines 2000-2150 ===" >> "$OUTFILE"
sed -n '2000,2150p' src/main.rs >> "$OUTFILE" 2>/dev/null
echo "DONE" >> "$OUTFILE"
cat "$OUTFILE"

#!/bin/bash
cd /Users/wesleysimplicio/simplicio-runtime
# Find the chat dispatch section
$HOME/.cargo/bin/cargo check 2>&1 | tail -5
echo "---"
# Find the chat dispatch line number
grep -n 'match sub' src/main.rs | head -10
echo "---"
# Read lines 2020-2080 where chat dispatch likely is
sed -n '2020,2080p' src/main.rs

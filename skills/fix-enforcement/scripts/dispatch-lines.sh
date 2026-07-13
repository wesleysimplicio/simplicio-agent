#!/bin/bash
cd /Users/wesleysimplicio/simplicio-runtime
sed -n '2070,2080p' src/main.rs
echo "---L2070-2080---"
sed -n '2080,2090p' src/main.rs
echo "---L2080-2090---"
sed -n '2090,2100p' src/main.rs
echo "---L2090-2100---"
sed -n '2100,2115p' src/main.rs
echo "---L2100-2115---"

#!/bin/bash
cd /Users/wesleysimplicio/simplicio-runtime
# Print the dispatch code section by section
echo "---SECTION 2080-2100---"
sed -n '2080,2100p' src/main.rs
echo "---SECTION 2100-2130---"
sed -n '2100,2130p' src/main.rs
echo "---SECTION 2130-2170---"
sed -n '2130,2170p' src/main.rs
echo "---SECTION 2440-2460---"
sed -n '2440,2460p' src/main.rs

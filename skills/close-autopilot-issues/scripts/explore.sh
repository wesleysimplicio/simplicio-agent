#!/bin/bash
set -e
DIR=/Users/wesleysimplicio/simplicio-runtime
cd "$DIR"
echo "=== Source Structure ==="
grep -n "fn main\|mod \|fn chat\|subcommand\|Command::\|\.subcommand(" src/main.rs | head -40
echo "=== Chat references ==="
grep -n -i "chat" src/main.rs | head -20
echo "=== Guardians ==="
grep -n -i "guardian\|isa\|helo\|levi" src/main.rs | head -30
#!/bin/bash
cd /Users/wesleysimplicio/simplicio-runtime
$HOME/.cargo/bin/cargo check 2>&1 | tail -30
echo "EXIT: $?"

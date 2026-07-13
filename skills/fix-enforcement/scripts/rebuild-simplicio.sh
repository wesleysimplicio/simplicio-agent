#!/bin/bash
set -e
export SIMPLICIO_ENFORCEMENT=0
cd /Users/wesleysimplicio/Projetos/ai/simplicio-runtime
echo "=== Limpando build ==="
cargo clean 2>&1
echo "=== Compilando release ==="
cargo build --release 2>&1
echo "=== Build exit: $? ==="
ls -la target/release/simplicio
echo "=== Testando binario ==="
target/release/simplicio --version 2>&1 && echo "BINARY OK" || echo "BINARY TEST FAILED"
echo "=== Copiando para ~/.local/bin/ ==="
cp target/release/simplicio ~/.local/bin/simplicio && echo "COPY OK" || echo "COPY FAILED"
echo "=== Verificando ==="
ls -la ~/.local/bin/simplicio
~/.local/bin/simplicio --version 2>&1 && echo "FINAL BINARY OK" || echo "FINAL BINARY TEST FAILED"

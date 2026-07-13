---
name: simplicio-agent-main-reflection
title: Verificar e refletir o main do simplicio-agent no bot vivo (~/.simplicio_agent)
description: Diagnóstico de topologia e verificação de ponta a ponta de que o repo `simplicio-agent` (main) está operante no gateway vivo cujo HERMES_HOME é `~/.simplicio_agent`. Inclui o pitfall mtime×checksum e o procedimento de sync skills repo→home.
---

# Verificar / refletir o main do `simplicio-agent` no bot vivo

Use quando o usuário perguntar "as modificações da main estão funcionando?", "pegamos as últimas atualizações da main?", ou "o bot está rodando a versão nova?".

## Topologia real (descobrir ANTES de afirmar qualquer coisa)

```
github.com/wesleysimplicio/simplicio-agent   (origin/main, commit X)
        │  git pull
        ▼
~/Projetos/ai/simplicio-agent/               ← repo: código hermes_cli/ + skills/
   ├─ hermes_cli/   → editable install no .venv (pip show mostra 0.24.0, não 0.15.2 Homebrew)
   └─ skills/       → copiadas para ↓
        ▼
~/.simplicio_agent/                           (HERMES_HOME do bot Simplicio)
   ├─ skills/        ← bot LÊ daqui (cópia, NÃO symlink)
   └─ config.yaml
        ▼
gateway PID (exec: .venv/bin/python -m hermes_cli.main, HERMES_HOME=~/.simplicio_agent)
```

Fatores que decidem se a main está "viva":
1. O repo `main` == `origin/main` (pull foi feito?).
2. O código é **editable install** (import vem do repo, não do site-packages fixo).
3. O `~/.simplicio_agent/skills/` tem os arquivos da main (byte-idênticos).
4. O **gateway vivo** iniciou APÓS o commit da main (ou foi reiniciado depois).

## Passo a passo de verificação (cadeia de evidência)

```bash
# 1) repo está em dia com origin/main?
cd ~/Projetos/ai/simplicio-agent
git remote -v
git branch --show-current                 # esperado: main
git rev-parse HEAD                        # deve == origin/main
git rev-parse origin/main

# 2) instalacao editable? (pip pode mostrar 0.15.2 no Homebrew e 0.24.0 no .venv)
/opt/homebrew/opt/python@3.11/bin/python3.11 -m pip show hermes-agent   # Homebrew: 0.15.2
.venv/bin/python3 -m pip show hermes-agent                                # repo venv: 0.24.0
cat .venv/lib/python3.11/site-packages/__editable__.hermes_agent-*.pth   # aponta pro repo
.venv/bin/python3 -c "import hermes_cli,os;print(os.path.dirname(hermes_cli.__file__))"  # deve ser .../simplicio-agent/hermes_cli

# 3) o que o ultimo commit da main tocou? (focar os arquivos certos)
git show --stat --oneline HEAD | head -40

# 4) skills do repo == skills do home? (lacuna real de sync)
diff -rq skills/ ~/.simplicio_agent/skills/
#  - "Only in ~/.simplicio_agent/skills: X" pode ser skill pip-extra (esperado, nao é lacuna)
#  - se um arquivo do REPO faltar no home => lacuna real

# 5) CHECKSUM (NAO mtime!) dos arquivos que a main tocou
for f in skills/asolaria-patterns/SKILL.md skills/asolaria-patterns/lib/behcs_supervisor.py; do
  r=$(shasum ~/Projetos/ai/simplicio-agent/$f | cut -d' ' -f1)
  h=$(shasum ~/.simplicio_agent/$f | cut -d' ' -f1)
  [ "$r" = "$h" ] && echo "IGUAL $f" || echo "DIFERE $f"
done

# 6) qual gateway esta vivo e de onde importa?
ps aux | grep -E "hermes_cli.main gateway" | grep -v grep
pid=$(pgrep -f "hermes_cli.main gateway" | head -1)
ps -E -p $pid | tr ' ' '\n' | grep -iE "HERMES_HOME|SIMPLICIO_AGENT_HOME"   # deve ser ~/.simplicio_agent
lsof -p $pid 2>/dev/null | grep -iE "hermes_cli|simplicio-agent/hermes_cli"  # confirma import do repo
ps -o lstart= -p $pid                                                     # inicio do gateway
git show -s --format=%ci HEAD                                             # data do commit da main
# gateway start > commit date  =>  main refletida no bot vivo
```

Ver detalhes de comando em `references/verification-recipe.md`.

## PITFALL — mtime é sinal falso, use checksum

Nesta sessão os `mtime` dos arquivos da main divergiam **16 minutos** (repo 15:26 vs home 15:10) mas o `shasum` era **idêntico**. Se eu tivesse confiado no mtime, teria concluído "não refletido" — erro. Regra: **nunca usar mtime para decidir se a main está no bot; use `shasum`/`diff -rq` de conteúdo.**

## Resposta honesta (formato)

Se tudo bater: `MEASURED| — Sim, a main está refletida` + tabela com as 6 verificações.
Se houver lacuna (arquivo do repo ausente no home): aponte o arquivo exato e ofereça o sync.

## Gap conhecido — sync é manual

Hoje não há auto-sync: um commit novo na main NÃO puxa sozinho pro `~/.simplicio_agent`. Procedimento manual (e candidato a `simplicio agent sync-main`):

```bash
# copia so as skills que o REPO controla, preservando as extras do home
rsync -a --ignore-existing ~/Projetos/ai/simplicio-agent/skills/ ~/.simplicio_agent/skills/
# depois reinicia o gateway do Simplicio bot (kill no PID + rerun do start script)
```

Não confunda com o runtime: este skill é sobre o **repo agente**, não o `simplicio-runtime`.

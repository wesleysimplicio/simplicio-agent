# verification-recipe.md — Comandos exatos usados e verificados (sessão 2026-07-08)

Todos os comandos abaixo foram executados de verdade nesta sessão e produziram as
saídas citadas. Copie/cole sem modificar.

## A. Estado do repo vs origin/main
```bash
cd /Users/wesleysimplicio/Projetos/ai/simplicio-agent
git remote -v            # origin https://github.com/wesleysimplicio/simplicio-agent.git
git branch --show-current # main
git rev-parse HEAD       # df90522130438add0529c0129213bc290fa8abee
git rev-parse origin/main # df90522130438add0529c0129213bc290fa8abee  (== HEAD OK)
```

## B. Instalação editable (repo vence Homebrew)
```bash
/opt/homebrew/opt/python@3.11/bin/python3.11 -m pip show hermes-agent | head -3
# Name: hermes-agent  Version: 0.15.2   (Homebrew — NAO e o usado pelo bot)

/Users/wesleysimplicio/Projetos/ai/simplicio-agent/.venv/bin/python3 -m pip show hermes-agent | head -3
# Name: hermes-agent  Version: 0.24.0   (repo venv — ESTE e o vivo)

cat /Users/wesleysimplicio/Projetos/ai/simplicio-agent/.venv/lib/python3.11/site-packages/__editable__.hermes_agent-0.24.0.pth
# import __editable___hermes_agent_0_24_0_finder; __editable___hermes_agent_0_24_0_finder.install()

.venv/bin/python3 -c "import hermes_cli,os;print(os.path.dirname(hermes_cli.__file__))"
# /Users/wesleysimplicio/Projetos/ai/simplicio-agent/hermes_cli  OK (editable aponta pro repo)
```

## C. O que a main tocou (focar nesses arquivos)
```bash
git show --stat --oneline HEAD | head -40
# df9052213 feat(asolaria): port N-Nest cosign, HRM planner, BEHCS supervisor, wormhole bridge
#   skills/asolaria-patterns/SKILL.md
#   skills/asolaria-patterns/lib/behcs_supervisor.py
#   skills/asolaria-patterns/lib/hierarchical_planner.py
#   skills/asolaria-patterns/lib/nest_cosign.py
#   skills/asolaria-patterns/lib/wormhole_bridge.py
#   skills/asolaria-patterns/tests/test_patterns.py
```

## D. Lacuna skills repo -> home
```bash
diff -rq skills/ ~/.simplicio_agent/skills/
# Linhas "Only in /Users/wesleysimplicio/.simplicio_agent/skills: X" = skill pip-extra (OK)
# Qualquer arquivo do REPO faltando no home = lacuna real de sync
```

## E. CHECKSUM (a prova definitiva — NAO mtime)
```bash
for f in SKILL.md lib/behcs_supervisor.py lib/hierarchical_planner.py lib/nest_cosign.py lib/wormhole_bridge.py; do
  r=$(shasum /Users/wesleysimplicio/Projetos/ai/simplicio-agent/skills/asolaria-patterns/$f | cut -d' ' -f1)
  h=$(shasum ~/.simplicio_agent/skills/asolaria-patterns/$f | cut -d' ' -f1)
  if [ "$r" = "$h" ]; then s="IGUAL"; else s="DIFERE"; fi
  printf '%-32s repo=%s home=%s => %s\n' "$f" "${r:0:8}" "${h:0:8}" "$s"
done
# TODOS IGUAL nesta sessao, apesar de mtime divergir 16 min (repo 15:26 vs home 15:10)
```

## F. Gateway vivo — qual importa e quando subiu
```bash
ps aux | grep -E "hermes_cli.main gateway" | grep -v grep
# PID 4409 = Simplicio bot (.venv no PATH, HERMES_HOME=~/.simplicio_agent)
# PID 81230 = AlfradHD (~/.hermes/hermes-agent/venv — OUTRO bot, ignorar)

pid=4409
ps -E -p $pid | tr ' ' '\n' | grep -iE "HERMES_HOME|SIMPLICIO_AGENT_HOME"
# HERMES_HOME=/Users/wesleysimplicio/.simplicio_agent  OK
# SIMPLICIO_AGENT_HOME=/Users/wesleysimplicio/.simplicio_agent  OK

lsof -p $pid 2>/dev/null | grep -iE "hermes_cli|simplicio-agent/hermes_cli"
# confirma import do repo editavel

ps -o lstart= -p $pid              # Wed Jul  8 16:29:28 2026
git show -s --format=%ci HEAD      # 2026-07-08 15:26:23 -0300
# gateway start (16:29) > commit (15:26)  =>  main refletida no bot vivo OK
```

## G. Start script (prova a ligacao bot->repo)
```bash
cat ~/.simplicio_agent/bin/start-simplicio-agent-discord.sh | head -12
# export SIMPLICIO_AGENT_HOME="/Users/wesleysimplicio/.simplicio_agent"
# export HERMES_HOME="/Users/wesleysimplicio/.simplicio_agent"
# PATH="/Users/wesleysimplicio/Projetos/ai/simplicio-agent/.venv/bin:..."
# cd /Users/wesleysimplicio/Projetos/ai/simplicio-agent
# exec python -m hermes_cli.main gateway run --replace
```

## H. Sync manual (gap — sem auto-pull)
```bash
rsync -a --ignore-existing ~/Projetos/ai/simplicio-agent/skills/ ~/.simplicio_agent/skills/
# reinicia o gateway: kill $pid ; ~/.simplicio_agent/bin/start-simplicio-agent-discord.sh &
```

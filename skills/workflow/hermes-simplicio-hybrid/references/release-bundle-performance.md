# Release bundle e performance — referência operacional

Use esta referência ao corrigir ou promover um bundle do `simplicio-agent`.

## Causa recorrente do fallback

O projeto pode declarar `orjson`/`msgspec` em um extra opcional, mas o bundle base não os recebe. Instalar apenas o projeto:

```bash
pip install "$DEST/code"
```

não equivale a instalar o extra:

```bash
pip install "$DEST/code[fast]"
```

O empacotador deve validar no venv do próprio bundle, não no Python do checkout:

```bash
"$DEST/venv/bin/python" -c 'import orjson, msgspec; print(orjson.__version__, msgspec.__version__)'
```

## Promoção segura

1. Registrar `current` e o `build-info.json` antes do build.
2. Criar uma nova pasta em `releases/<version>`; não sobrescrever o bundle ativo.
3. Usar `PIP_NO_CACHE_DIR=1` se houver pressão de disco.
4. Instalar `[fast]` e falhar se os imports obrigatórios não funcionarem.
5. Validar o módulo carregado pelo novo venv (`Path(module.__file__)`).
6. Comparar o helper com stdlib usando o mesmo payload; reportar ganho do helper, não do gateway inteiro.
7. Reapontar `current` somente após os gates.
8. Verificar o processo do gateway: symlink novo não altera módulos Python já carregados. `__PYVENV_LAUNCHER__`, PID e horário de início revelam qual bundle está efetivamente em execução.
9. Ativar o novo código usando `/restart` pelo Discord; não usar `launchctl unload/load/kickstart` de dentro do gateway.

## Watchdog e cron

- Listar os cronjobs e confirmar o `job_id`, nome, prompt e schedule antes de pausar.
- O watchdog deve comparar `current/build-info.json.version` com a última tag do projeto.
- Filtrar tags que pertencem ao projeto; tags calendar-version de um upstream podem parecer releases mais novas.
- Em release igual, o watchdog deve sair sem build.
- Em release diferente, deve passar explicitamente `--version` e `--ref` para o builder.
- Não usar um estado antigo como única fonte de verdade: o bundle implantado é a fonte primária.

## Evidência mínima

```text
bundle novo: current -> releases/<version>
import orjson/msgspec: passou no venv do bundle
helper: benchmark com números reais
processo: PID + launcher/ambiente verificados
cron: job_id e estado pausado confirmados
```

Não declarar melhoria ponta a ponta sem um benchmark comparável do gateway; um ganho de JSON é apenas um ganho de componente.

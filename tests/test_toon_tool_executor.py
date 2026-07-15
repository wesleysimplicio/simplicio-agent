"""Testes do chokepoint TOON no tool_executor (issue #16).

Verifica que:
1. maybe_toon_encode_tool_result converte resultados JSON reais
2. A telemetria (record_token_saving) recebe eventos reais de produção
3. Ferramentas na lista de exceção passam inalteradas
4. Resultados não-JSON passam inalterados
5. O flag de sessão é respeitado (off = noop)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.toon_boundary import TOON_EXEMPT_TOOLS, maybe_toon_encode_tool_result
from agent.toon_codec import from_toon
from agent.telemetry.token_savings import iter_records


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_telemetry_log(tmp_path, monkeypatch):
    """Redireciona o JSONL de telemetria para um arquivo temporário."""
    log_path = tmp_path / "token_savings.jsonl"
    monkeypatch.setenv("HERMES_TOKEN_SAVINGS_LOG", str(log_path))
    return log_path


def _make_agent(**kwargs) -> SimpleNamespace:
    defaults = dict(
        _toon_prompts_enabled=True,
        model="claude-3-5-sonnet",
        provider="anthropic",
        session_id="test-session-42",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Testes: conversão no chokepoint
# ---------------------------------------------------------------------------

def test_chokepoint_converte_dict_json_para_toon():
    """Resultado dict JSON retornado por tool deve ser convertido para TOON."""
    agent = _make_agent()
    raw = json.dumps({"status": "ok", "files_modified": ["agent/foo.py", "tests/foo.py"]})
    out = maybe_toon_encode_tool_result(agent, "write_file", raw)

    # Deve ter mudado
    assert out != raw
    # Deve ser lossless
    decoded = from_toon(out)
    assert decoded["status"] == "ok"
    assert decoded["files_modified"] == ["agent/foo.py", "tests/foo.py"]


def test_chokepoint_converte_lista_uniforme_de_objetos():
    """Arrays uniformes (padrão common de tools de busca) devem ser comprimidos."""
    agent = _make_agent()
    payload = [
        {"file": "a.py", "line": 10, "match": "foo"},
        {"file": "b.py", "line": 20, "match": "bar"},
        {"file": "c.py", "line": 30, "match": "baz"},
    ]
    raw = json.dumps(payload)
    out = maybe_toon_encode_tool_result(agent, "search_files", raw)

    assert out != raw
    decoded = from_toon(out)
    assert decoded == payload


def test_chokepoint_noop_quando_flag_desativado():
    """Com _toon_prompts_enabled=False o resultado não deve ser alterado."""
    agent = _make_agent(_toon_prompts_enabled=False)
    raw = json.dumps({"error": "not found"})
    out = maybe_toon_encode_tool_result(agent, "read_file", raw)
    assert out == raw


def test_chokepoint_noop_para_ferramentas_isentas():
    """Ferramentas em TOON_EXEMPT_TOOLS devem passar inalteradas."""
    agent = _make_agent()
    for tool in TOON_EXEMPT_TOOLS:
        raw = json.dumps({"todos": [{"id": 1, "content": "test", "status": "pending", "priority": "high"}]})
        out = maybe_toon_encode_tool_result(agent, tool, raw)
        assert out == raw, f"Ferramenta isenta {tool!r} foi modificada indevidamente"


def test_chokepoint_noop_para_resultado_nao_json():
    """Strings que não são JSON (texto livre, blocos <persisted-output>) passam sem modificação."""
    agent = _make_agent()
    plain_text = "Processo concluído com sucesso.\nArquivos: 3 modificados."
    out = maybe_toon_encode_tool_result(agent, "terminal", plain_text)
    assert out == plain_text

    persisted = "<persisted-output id='abc123'>…</persisted-output>"
    out2 = maybe_toon_encode_tool_result(agent, "terminal", persisted)
    assert out2 == persisted


# ---------------------------------------------------------------------------
# Testes: telemetria reativada (ledger recebe eventos reais)
# ---------------------------------------------------------------------------

def test_telemetria_recebe_evento_real_apos_conversao(tmp_path, monkeypatch):
    """Após conversão TOON, o ledger JSONL deve conter exatamente 1 evento."""
    log_path = tmp_path / "savings.jsonl"
    monkeypatch.setenv("HERMES_TOKEN_SAVINGS_LOG", str(log_path))

    agent = _make_agent()
    raw = json.dumps({"tool": "terminal", "output": "ok", "exit_code": 0})
    maybe_toon_encode_tool_result(agent, "terminal", raw, session_id="sess-tel-1")

    assert log_path.exists(), "JSONL de telemetria não foi criado"
    records = list(iter_records(log_path))
    assert len(records) == 1
    rec = records[0]
    assert rec["tool"] == "terminal"
    assert rec["command"] == "tool_executor.boundary"
    assert rec["raw_tokens"] > 0
    assert rec["compressed_tokens"] > 0
    # Resultado comprimido deve ser <= original (TOON never expands para payloads simples)
    assert rec["compressed_tokens"] <= rec["raw_tokens"]


def test_telemetria_nao_gera_evento_quando_flag_off(tmp_path, monkeypatch):
    """Sem flag ativo nenhum evento deve ser escrito no ledger."""
    log_path = tmp_path / "savings.jsonl"
    monkeypatch.setenv("HERMES_TOKEN_SAVINGS_LOG", str(log_path))

    agent = _make_agent(_toon_prompts_enabled=False)
    raw = json.dumps({"a": 1})
    maybe_toon_encode_tool_result(agent, "read_file", raw)

    # Nenhum arquivo criado ou arquivo vazio
    if log_path.exists():
        assert log_path.read_text().strip() == ""


def test_telemetria_acumula_multiplos_eventos(tmp_path, monkeypatch):
    """Cada chamada ao chokepoint gera um evento separado no ledger."""
    log_path = tmp_path / "savings.jsonl"
    monkeypatch.setenv("HERMES_TOKEN_SAVINGS_LOG", str(log_path))

    agent = _make_agent()
    tools_and_payloads = [
        ("read_file", {"content": "x" * 100, "lines": list(range(20))}),
        ("search_files", [{"path": f"file{i}.py", "line": i, "match": "foo"} for i in range(5)]),
        ("terminal", {"output": "Done", "exit_code": 0, "duration_ms": 123}),
    ]
    for tool, payload in tools_and_payloads:
        maybe_toon_encode_tool_result(agent, tool, json.dumps(payload))

    records = list(iter_records(log_path))
    assert len(records) == 3, f"Esperado 3 eventos, obtido {len(records)}"
    tool_names = [r["tool"] for r in records]
    assert "read_file" in tool_names
    assert "search_files" in tool_names
    assert "terminal" in tool_names

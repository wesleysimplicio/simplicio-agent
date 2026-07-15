"""Testes de documentação para defaults de performance (issue #10)."""
from pathlib import Path
import pytest

REPO = Path(__file__).parent.parent
DOC = REPO / "docs" / "perf-defaults.md"


def test_doc_exists():
    """docs/perf-defaults.md existe."""
    assert DOC.exists(), f"doc não encontrado: {DOC}"


def test_doc_has_required_sections():
    """Doc tem seções obrigatórias da AC da issue #10."""
    content = DOC.read_text()
    required = [
        "## Mapa de módulos",
        "## Como verificar o estado atual",
        "## Como ativar todos os módulos",
        "## Toggles por variável de ambiente",
        "## Checklist de revisão",
    ]
    for section in required:
        assert section in content, f"Seção ausente: {section}"


def test_doc_covers_core_modules():
    """Doc menciona os módulos core de performance."""
    content = DOC.read_text()
    modules = [
        "orjson", "tiktoken", "simplicio_fast",
        "token_saver", "telemetria", "working set",
    ]
    for m in modules:
        assert m.lower() in content.lower(), f"Módulo não documentado: {m}"


def test_doc_has_env_vars():
    """Doc lista as variáveis de ambiente de toggle."""
    content = DOC.read_text()
    env_vars = [
        "SIMPLICIO_TOKEN_SAVER",
        "SIMPLICIO_TELEMETRY",
        "SIMPLICIO_LAZY_SCHEMA",
        "SIMPLICIO_GATE_SKIP",
    ]
    for v in env_vars:
        assert v in content, f"Variável de ambiente não documentada: {v}"


def test_env_toggle_detection():
    """Detecta módulos opcionais via importação (sem falhar se ausentes)."""
    import importlib.util
    results = {}
    for pkg in ["orjson", "tiktoken", "msgspec"]:
        spec = importlib.util.find_spec(pkg)
        results[pkg] = spec is not None

    # Não falha — apenas verifica que a detecção funciona
    assert isinstance(results, dict)
    assert set(results.keys()) == {"orjson", "tiktoken", "msgspec"}
    print(f"\n  Módulos opcionais detectados: {results}")

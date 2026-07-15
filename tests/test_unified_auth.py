"""
tests/test_unified_auth.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Testes para agent/security/unified_auth.py (issue #46).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from agent.security.unified_auth import (
    EnvSecretProvider,
    FileSecretProvider,
    UnifiedSecretManager,
)


# ---------------------------------------------------------------------------
# EnvSecretProvider
# ---------------------------------------------------------------------------

class TestEnvSecretProvider:
    def test_retorna_valor_existente(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET_KEY", "valor_secreto")
        provider = EnvSecretProvider()
        assert provider.get_secret("MY_SECRET_KEY") == "valor_secreto"

    def test_retorna_none_para_chave_ausente(self):
        provider = EnvSecretProvider()
        resultado = provider.get_secret("__CHAVE_QUE_NAO_EXISTE__")
        assert resultado is None


# ---------------------------------------------------------------------------
# FileSecretProvider
# ---------------------------------------------------------------------------

class TestFileSecretProvider:
    def _criar_env(self, conteudo: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False, encoding="utf-8"
        )
        tmp.write(conteudo)
        tmp.close()
        return Path(tmp.name)

    def test_le_par_simples(self):
        path = self._criar_env("API_KEY=minha_chave\n")
        provider = FileSecretProvider(path)
        assert provider.get_secret("API_KEY") == "minha_chave"

    def test_ignora_comentarios_e_linhas_vazias(self):
        conteudo = "\n# comentário\nDB_PASS=senha123\n\n"
        path = self._criar_env(conteudo)
        provider = FileSecretProvider(path)
        assert provider.get_secret("DB_PASS") == "senha123"

    def test_remove_aspas_duplas(self):
        path = self._criar_env('TOKEN="abc123"\n')
        provider = FileSecretProvider(path)
        assert provider.get_secret("TOKEN") == "abc123"

    def test_remove_aspas_simples(self):
        path = self._criar_env("TOKEN='xyz'\n")
        provider = FileSecretProvider(path)
        assert provider.get_secret("TOKEN") == "xyz"

    def test_retorna_none_para_arquivo_ausente(self):
        provider = FileSecretProvider("/arquivo/que/nao/existe.env")
        assert provider.get_secret("QUALQUER") is None

    def test_retorna_none_para_chave_ausente_no_arquivo(self):
        path = self._criar_env("OUTRA_CHAVE=valor\n")
        provider = FileSecretProvider(path)
        assert provider.get_secret("CHAVE_INEXISTENTE") is None


# ---------------------------------------------------------------------------
# UnifiedSecretManager
# ---------------------------------------------------------------------------

class TestUnifiedSecretManager:
    def test_retorna_none_sem_providers(self):
        mgr = UnifiedSecretManager()
        assert mgr.get("QUALQUER") is None

    def test_provider_unico(self, monkeypatch):
        monkeypatch.setenv("USM_KEY", "hello")
        mgr = UnifiedSecretManager()
        mgr.register_provider(EnvSecretProvider())
        assert mgr.get("USM_KEY") == "hello"

    def test_prioridade_primeiro_provider(self, monkeypatch, tmp_path):
        # Env tem prioridade sobre arquivo
        monkeypatch.setenv("PRIO_KEY", "env_valor")
        env_file = tmp_path / ".env"
        env_file.write_text("PRIO_KEY=file_valor\n")

        mgr = UnifiedSecretManager()
        mgr.register_provider(EnvSecretProvider())
        mgr.register_provider(FileSecretProvider(env_file))

        assert mgr.get("PRIO_KEY") == "env_valor"

    def test_fallback_para_segundo_provider(self, tmp_path):
        # Chave não existe no env, mas existe no arquivo
        key = "__FALLBACK_TEST_KEY_ISSUE46__"
        os.environ.pop(key, None)  # garantir ausência

        env_file = tmp_path / ".env"
        env_file.write_text(f"{key}=file_fallback\n")

        mgr = UnifiedSecretManager()
        mgr.register_provider(EnvSecretProvider())
        mgr.register_provider(FileSecretProvider(env_file))

        assert mgr.get(key) == "file_fallback"

    def test_retorna_none_quando_nenhum_provider_conhece_chave(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("OUTRO=valor\n")

        mgr = UnifiedSecretManager()
        mgr.register_provider(EnvSecretProvider())
        mgr.register_provider(FileSecretProvider(env_file))

        assert mgr.get("__NAO_EXISTE_EM_NENHUM__") is None

"""
agent/security/unified_auth.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Segurança Unificada — issue #46.

Classes
-------
SecretProvider          ABC base para qualquer fonte de segredos.
EnvSecretProvider       Lê segredos de variáveis de ambiente (os.environ).
FileSecretProvider      Lê segredos de um arquivo .env (KEY=VALUE, stdlib only).
UnifiedSecretManager    Itera providers em ordem de registro e retorna o primeiro valor encontrado.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional


class SecretProvider(ABC):
    """Interface base para provedores de segredos."""

    @abstractmethod
    def get_secret(self, key: str) -> Optional[str]:
        """Retorna o valor do segredo ou None se não encontrado."""


class EnvSecretProvider(SecretProvider):
    """Provedor que lê segredos de variáveis de ambiente."""

    def get_secret(self, key: str) -> Optional[str]:
        return os.environ.get(key)


class FileSecretProvider(SecretProvider):
    """Provedor que lê segredos de um arquivo .env (KEY=VALUE).

    - Linhas em branco e comentários (# ...) são ignorados.
    - Aspas simples/duplas ao redor do valor são removidas.
    - Usa apenas stdlib; nenhuma dependência externa.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._cache: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.is_file():
            return
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                # Remove aspas opcionais
                if len(v) >= 2 and v[0] in ('"', "'") and v[-1] == v[0]:
                    v = v[1:-1]
                if k:
                    self._cache[k] = v

    def get_secret(self, key: str) -> Optional[str]:
        self._load()
        return self._cache.get(key)


class UnifiedSecretManager:
    """Gerenciador unificado que itera providers em ordem de registro."""

    def __init__(self) -> None:
        self._providers: List[SecretProvider] = []

    def register_provider(self, provider: SecretProvider) -> None:
        """Registra um provider; providers registrados primeiro têm prioridade."""
        self._providers.append(provider)

    def get(self, key: str) -> Optional[str]:
        """Retorna o valor do primeiro provider que conhece a chave."""
        for provider in self._providers:
            value = provider.get_secret(key)
            if value is not None:
                return value
        return None

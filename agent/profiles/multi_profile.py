"""
Sistema Multi-Profile para Simplicio Agent.

Armazena perfis em ~/.simplicio/profiles/<name>.json usando stdlib apenas.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List


@dataclass
class AgentProfile:
    """Configuração de um perfil de agente."""

    name: str
    model: str
    system_prompt: str
    tools: List[str] = field(default_factory=list)
    home_dir: Path = field(default_factory=lambda: Path.home())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["home_dir"] = str(self.home_dir)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AgentProfile":
        data = dict(data)
        data["home_dir"] = Path(data.get("home_dir", Path.home()))
        return cls(**data)


class ProfileManager:
    """Gerencia perfis de agente armazenados em ~/.simplicio/profiles/."""

    _ACTIVE_FILE = "active_profile"

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path.home() / ".simplicio" / "profiles"
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _profile_path(self, name: str) -> Path:
        return self._base_dir / f"{name}.json"

    def _active_path(self) -> Path:
        return self._base_dir / self._ACTIVE_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, profile: AgentProfile) -> None:
        """Persiste um novo perfil (ou sobrescreve existente)."""
        path = self._profile_path(profile.name)
        path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")

    def load(self, name: str) -> AgentProfile:
        """Carrega um perfil pelo nome. Levanta FileNotFoundError se ausente."""
        path = self._profile_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Perfil '{name}' não encontrado em {self._base_dir}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentProfile.from_dict(data)

    def list_profiles(self) -> List[str]:
        """Retorna nomes de todos os perfis salvos (sem extensão .json)."""
        return sorted(p.stem for p in self._base_dir.glob("*.json"))

    def switch(self, name: str) -> None:
        """Define o perfil ativo. Levanta FileNotFoundError se o perfil não existe."""
        if not self._profile_path(name).exists():
            raise FileNotFoundError(f"Perfil '{name}' não encontrado em {self._base_dir}")
        self._active_path().write_text(name, encoding="utf-8")

    def active_profile(self) -> AgentProfile:
        """Retorna o perfil ativo atual. Levanta RuntimeError se nenhum foi definido."""
        active_file = self._active_path()
        if not active_file.exists():
            raise RuntimeError("Nenhum perfil ativo definido. Use switch() primeiro.")
        name = active_file.read_text(encoding="utf-8").strip()
        return self.load(name)

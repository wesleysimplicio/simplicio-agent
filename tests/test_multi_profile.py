"""Testes para o sistema multi-profile (issue #45)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.profiles.multi_profile import AgentProfile, ProfileManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager(tmp_path: Path) -> ProfileManager:
    """ProfileManager isolado usando diretório temporário."""
    return ProfileManager(base_dir=tmp_path / "profiles")


@pytest.fixture()
def sample_profile() -> AgentProfile:
    return AgentProfile(
        name="simplicio",
        model="claude-sonnet-4-6",
        system_prompt="Você é o Simplicio Agent.",
        tools=["bash", "read_file"],
        home_dir=Path("/tmp/simplicio_home"),
    )


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------


def test_create_and_load_profile(manager: ProfileManager, sample_profile: AgentProfile) -> None:
    """Criar um perfil e recarregá-lo deve produzir objeto idêntico."""
    manager.create(sample_profile)
    loaded = manager.load(sample_profile.name)

    assert loaded.name == sample_profile.name
    assert loaded.model == sample_profile.model
    assert loaded.system_prompt == sample_profile.system_prompt
    assert loaded.tools == sample_profile.tools
    assert loaded.home_dir == sample_profile.home_dir


def test_list_profiles(manager: ProfileManager) -> None:
    """list_profiles() deve retornar os nomes de todos os perfis criados."""
    profiles = [
        AgentProfile(name="alfa", model="gpt-4o", system_prompt="p1", tools=[], home_dir=Path("/tmp/a")),
        AgentProfile(name="beta", model="claude-3", system_prompt="p2", tools=[], home_dir=Path("/tmp/b")),
        AgentProfile(name="gamma", model="gemini-2", system_prompt="p3", tools=[], home_dir=Path("/tmp/c")),
    ]
    for p in profiles:
        manager.create(p)

    names = manager.list_profiles()
    assert names == ["alfa", "beta", "gamma"]


def test_switch_and_active_profile(manager: ProfileManager, sample_profile: AgentProfile) -> None:
    """switch() + active_profile() devem retornar o perfil correto."""
    manager.create(sample_profile)
    manager.switch(sample_profile.name)
    active = manager.active_profile()

    assert active.name == sample_profile.name
    assert active.model == sample_profile.model


def test_load_nonexistent_raises(manager: ProfileManager) -> None:
    """Carregar perfil inexistente deve levantar FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="inexistente"):
        manager.load("inexistente")


def test_switch_nonexistent_raises(manager: ProfileManager) -> None:
    """switch() para perfil inexistente deve levantar FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        manager.switch("ghost")


def test_active_profile_without_switch_raises(manager: ProfileManager) -> None:
    """active_profile() sem switch prévio deve levantar RuntimeError."""
    with pytest.raises(RuntimeError, match="Nenhum perfil ativo"):
        manager.active_profile()


def test_create_overwrites_existing(manager: ProfileManager, sample_profile: AgentProfile) -> None:
    """Criar novamente com mesmo nome deve sobrescrever o perfil."""
    manager.create(sample_profile)

    updated = AgentProfile(
        name=sample_profile.name,
        model="claude-opus-4",
        system_prompt="Prompt atualizado",
        tools=["write_file"],
        home_dir=Path("/tmp/new_home"),
    )
    manager.create(updated)
    loaded = manager.load(sample_profile.name)

    assert loaded.model == "claude-opus-4"
    assert loaded.system_prompt == "Prompt atualizado"

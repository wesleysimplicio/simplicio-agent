"""Public Simplicio Agent facade regressions for issue #190."""

from __future__ import annotations

import glob
import importlib
import json
import os
import subprocess
import sys
import textwrap
import types
import venv
import warnings
from importlib import resources
from pathlib import Path

import pytest

import simplicio_agent
import simplicio_agent.compat as compat

REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_stub_modules(monkeypatch):
    run_agent = types.ModuleType("run_agent")
    cli_module = types.ModuleType("cli")
    main_module = types.ModuleType("hermes_cli.main")

    class StubAgent:
        pass

    class StubCLI:
        pass

    def stub_main():
        return "ok"

    run_agent.AIAgent = StubAgent
    cli_module.HermesCLI = StubCLI
    main_module.main = stub_main

    monkeypatch.setattr(simplicio_agent, "import_module", importlib.import_module)
    monkeypatch.setitem(sys.modules, "run_agent", run_agent)
    monkeypatch.setitem(sys.modules, "cli", cli_module)
    monkeypatch.setitem(sys.modules, "hermes_cli.main", main_module)

    return StubAgent, StubCLI, stub_main


def test_public_facade_exports_canonical_symbols_without_wrapping(monkeypatch):
    stub_agent, stub_cli, stub_main = _install_stub_modules(monkeypatch)

    assert simplicio_agent.Agent is stub_agent
    assert simplicio_agent.CLI is stub_cli
    assert simplicio_agent.main is stub_main
    assert simplicio_agent.Agent.__module__ == __name__
    assert simplicio_agent.CLI.__module__ == __name__
    assert resources.files("simplicio_agent").joinpath("py.typed").is_file()
    package_files = resources.files("simplicio_agent")
    assert package_files.joinpath("__init__.pyi").is_file()
    assert package_files.joinpath("compat.pyi").is_file()


def test_public_facade_metadata_and_unknown_names(monkeypatch):
    stub_agent, stub_cli, _ = _install_stub_modules(monkeypatch)
    from hermes_cli import __release_date__, __version__

    assert simplicio_agent.__version__ == __version__
    assert simplicio_agent.__release_date__ == __release_date__
    assert set((
        "Agent",
        "CLI",
        "main",
        "asolaria",
        "__version__",
        "__release_date__",
    )) <= set(simplicio_agent.__all__)
    assert simplicio_agent.Agent is stub_agent is simplicio_agent.Agent
    assert simplicio_agent.CLI is stub_cli is simplicio_agent.CLI
    with pytest.raises(AttributeError):
        _ = simplicio_agent.not_a_public_export


def test_compat_legacy_aliases_warn_and_preserve_identity(monkeypatch):
    stub_agent, stub_cli, _ = _install_stub_modules(monkeypatch)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        legacy_agent = compat.AIAgent
        legacy_cli = compat.HermesCLI

    assert legacy_agent is simplicio_agent.Agent is stub_agent
    assert legacy_cli is simplicio_agent.CLI is stub_cli
    assert [type(item.message) for item in caught] == [
        DeprecationWarning,
        DeprecationWarning,
    ]
    assert "simplicio_agent.Agent" in str(caught[0].message)
    assert "simplicio_agent.CLI" in str(caught[1].message)
    with pytest.raises(AttributeError):
        _ = compat.not_a_legacy_export


@pytest.mark.parametrize("canonical_first", [True, False])
def test_public_module_import_order_preserves_legacy_identity(
    canonical_first,
):
    stub_loader = """
        import importlib.abc
        import importlib.util
        import sys

        load_counts = {name: 0 for name in ("run_agent", "cli", "hermes_cli.main")}

        class StubLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in load_counts:
                    return importlib.util.spec_from_loader(fullname, self)
                return None

            def exec_module(self, module):
                load_counts[module.__name__] += 1
                if module.__name__ == "run_agent":
                    module.AIAgent = type("AIAgent", (), {})
                elif module.__name__ == "cli":
                    module.HermesCLI = type("HermesCLI", (), {})
                else:
                    module.main = lambda: None

        sys.meta_path.insert(0, StubLoader())
    """
    canonical_imports = """
        import simplicio_agent
        Agent = simplicio_agent.Agent
        CLI = simplicio_agent.CLI
        main = simplicio_agent.main
    """
    legacy_imports = """
        from run_agent import AIAgent
        from cli import HermesCLI
        from hermes_cli.main import main as legacy_main
    """
    ordered_imports = (
        (canonical_imports, legacy_imports)
        if canonical_first
        else (legacy_imports, canonical_imports)
    )
    assertions = """
        assert Agent is AIAgent
        assert CLI is HermesCLI
        assert main is legacy_main
        assert load_counts == {
            "run_agent": 1,
            "cli": 1,
            "hermes_cli.main": 1,
        }
    """
    probe = "\n".join(
        textwrap.dedent(part)
        for part in (stub_loader, *ordered_imports, assertions)
    )
    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, (
        f"import-order probe failed:\nstdout: {run.stdout}\nstderr: {run.stderr}"
    )


def _create_supported_venv(venv_dir: Path) -> Path:
    if sys.version_info < (3, 14):
        venv.create(venv_dir, with_pip=True)
        return venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"

    probe = subprocess.run(
        ["uv", "python", "find", "3.13"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert probe.returncode == 0, f"uv python find 3.13 failed:\n{probe.stderr}"
    subprocess.run(
        ["uv", "venv", "--python", "3.13", "--seed", str(venv_dir)],
        check=True,
        timeout=300,
    )
    return venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"


@pytest.mark.integration
def test_installed_wheel_exposes_facade_and_py_typed(tmp_path):
    wheel_dir = tmp_path / "wheel"
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir), "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, f"uv build failed:\n{build.stderr}"
    wheels = glob.glob(str(wheel_dir / "*.whl"))
    assert wheels, "no wheel produced"

    venv_dir = tmp_path / "venv"
    vpy = _create_supported_venv(venv_dir)
    subprocess.run(
        [str(vpy), "-m", "pip", "install", "-q", "--force-reinstall", wheels[0]],
        check=True,
        timeout=600,
    )

    probe = textwrap.dedent(
        """
        import json
        import warnings
        from importlib import resources

        import simplicio_agent
        import simplicio_agent.compat as compat
        from cli import HermesCLI
        from run_agent import AIAgent

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            legacy_agent = compat.AIAgent
            legacy_cli = compat.HermesCLI

        payload = {
            "agent_identity": simplicio_agent.Agent is AIAgent is legacy_agent,
            "cli_identity": simplicio_agent.CLI is HermesCLI is legacy_cli,
            "py_typed": resources.files("simplicio_agent").joinpath("py.typed").is_file(),
            "warning_count": len(caught),
        }
        print(json.dumps(payload))
        raise SystemExit(0 if all(payload.values()) else 1)
        """
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    run = subprocess.run(
        [str(vpy), "-c", probe],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        timeout=240,
    )
    assert run.returncode == 0, (
        "installed wheel facade probe failed:\n"
        f"stdout: {run.stdout}\n"
        f"stderr: {run.stderr}"
    )
    payload = json.loads(run.stdout.strip())
    assert payload == {
        "agent_identity": True,
        "cli_identity": True,
        "py_typed": True,
        "warning_count": 2,
    }

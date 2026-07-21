"""AST-based anti-fake-success gate for agent execution handlers.

The gate is deliberately structural.  It does not execute application code or
infer intent from arbitrary strings; it catches the two patterns that can make
an agent appear to have completed work without doing it: silent placeholder
handlers and unconditional synthetic success responses.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AntiFakeViolation:
    path: str
    line: int
    function: str
    kind: str
    message: str


class AntiFakeGateError(RuntimeError):
    """Raised when the anti-fake gate finds a production violation."""

    def __init__(self, violations: Iterable[AntiFakeViolation]) -> None:
        self.violations = tuple(violations)
        super().__init__(
            "anti-fake gate failed: "
            + "; ".join(
                f"{item.path}:{item.line} {item.kind}" for item in self.violations
            )
        )


_HANDLER_MARKERS = ("handler", "handle", "execute", "dispatch", "invoke", "tool")
_SUCCESS_KEYS = {"ok", "success", "status", "decision"}


def _is_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    name = node.name.casefold()
    return any(marker in name for marker in _HANDLER_MARKERS)


def _is_contract_hook(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Allow abstract and intentionally empty lifecycle extension hooks."""
    if node.name.casefold().startswith(("_before_", "_after_")):
        return True
    return any(
        isinstance(decorator, ast.Name) and decorator.id == "abstractmethod"
        for decorator in node.decorator_list
    )


def _body_without_docstring(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.stmt]:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            body.pop(0)
    return body


def _constant(node: ast.AST) -> object:
    return node.value if isinstance(node, ast.Constant) else object()


def _synthetic_success_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _body_without_docstring(node)
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    value = body[0].value
    if not isinstance(value, ast.Dict) or not value.keys:
        return False

    for key, item in zip(value.keys, value.values):
        key_value = _constant(key)
        if not isinstance(key_value, str) or key_value.casefold() not in _SUCCESS_KEYS:
            continue
        item_value = _constant(item)
        if key_value.casefold() in {"ok", "success"} and item_value is True:
            return True
        if key_value.casefold() == "status" and item_value in {
            "success",
            "passed",
            "done",
            "completed",
        }:
            return True
        if key_value.casefold() == "decision" and item_value == "allow":
            return True
    return False


def scan_file(path: str | Path) -> tuple[AntiFakeViolation, ...]:
    source_path = Path(path)
    try:
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
    except (OSError, SyntaxError) as exc:
        return (
            AntiFakeViolation(
                str(source_path),
                getattr(exc, "lineno", 1) or 1,
                "<module>",
                "unreadable-source",
                str(exc),
            ),
        )

    violations: list[AntiFakeViolation] = []
    for node in ast.walk(tree):
        if (
            not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            or not _is_handler(node)
            or _is_contract_hook(node)
        ):
            continue
        body = _body_without_docstring(node)
        if (
            len(body) == 1
            and isinstance(body[0], (ast.Pass, ast.Expr))
            and (
                isinstance(body[0], ast.Pass)
                or isinstance(body[0].value, ast.Constant)
                and body[0].value.value is Ellipsis
            )
        ):
            violations.append(
                AntiFakeViolation(
                    str(source_path),
                    node.lineno,
                    node.name,
                    "silent-pass",
                    "handler has no observable implementation",
                )
            )
        elif _synthetic_success_return(node):
            violations.append(
                AntiFakeViolation(
                    str(source_path),
                    node.lineno,
                    node.name,
                    "synthetic-success",
                    "handler returns unconditional success without execution evidence",
                )
            )
    return tuple(violations)


def _python_files(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    files: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file() and path.suffix == ".py":
            files.add(path)
        elif path.is_dir():
            files.update(
                candidate
                for candidate in path.rglob("*.py")
                if "__pycache__" not in candidate.parts
                and "tests" not in candidate.parts
            )
    return tuple(sorted(files, key=lambda item: str(item)))


def scan_paths(paths: Iterable[str | Path]) -> list[AntiFakeViolation]:
    violations: list[AntiFakeViolation] = []
    for path in _python_files(paths):
        violations.extend(scan_file(path))
    return violations


def assert_no_fake_success(paths: Iterable[str | Path]) -> None:
    violations = scan_paths(paths)
    if violations:
        raise AntiFakeGateError(violations)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path", action="append", dest="paths", default=["agent", "tools"]
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    violations = scan_paths(args.paths)
    if args.as_json:
        print(json.dumps([asdict(item) for item in violations], sort_keys=True))
    else:
        if violations:
            for item in violations:
                print(f"{item.path}:{item.line}: {item.kind}: {item.message}")
        else:
            print("anti-fake gate: PASS")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "AntiFakeGateError",
    "AntiFakeViolation",
    "assert_no_fake_success",
    "scan_file",
    "scan_paths",
]

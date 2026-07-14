"""Bounded, additive import contract for the Asolaria patterns in issue #125.

The contract records the identity and scientific basis of one N-Nest or
PRISM-COMB import.  It validates caller-supplied metadata only: it does not
load pattern code, access the network, run a benchmark, or claim integration
with ``simplicio-runtime``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import json
import re
from typing import Any, Final


ISSUE_NUMBER: Final[int] = 125
SCHEMA: Final[str] = "simplicio.asolaria-pattern-import/v1"
CONTRACT_SCHEMA: Final[str] = SCHEMA
IMPORT_BOUNDARY: Final[str] = (
    "metadata gate only; no pattern execution and no simplicio-runtime integration"
)
MAX_TEXT_LENGTH: Final[int] = 8_192
MAX_ITEMS: Final[int] = 32
MAX_ERRORS: Final[int] = 64
_REVISION_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_TOKEN_RE = re.compile(r"^[^\x00-\x1f\x7f\s]+$")
_NO_LICENSE = frozenset({"no license", "no-license", "noassertion", "all-rights-reserved"})


class PatternName(StrEnum):
    """Pattern identities permitted by this import gate."""

    N_NEST = "N-Nest"
    PRISM_COMB = "PRISM-COMB"


class ImportMode(StrEnum):
    """How source bytes may be used under the declared license basis."""

    REIMPLEMENTATION = "reimplementation"
    PERMISSIVE = "permissive"


class AsolariaPatternContractError(ValueError):
    """Raised when a caller requires a manifest that failed closed."""


@dataclass(frozen=True, slots=True)
class PatternIdentity:
    """Stable name and bounded description for one imported pattern."""

    name: PatternName
    version: str
    summary: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _pattern_name(self.name, "identity.name"))
        _text(self.version, "identity.version", token=True)
        _text(self.summary, "identity.summary")


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Immutable source and evidence references for a pattern reimplementation."""

    pattern: PatternName
    repository: str
    url: str
    path: str
    revision: str
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pattern", _pattern_name(self.pattern, "source.pattern"))
        for name in ("repository", "url", "path"):
            _text(getattr(self, name), f"source.{name}")
        _revision(self.revision, "source.revision")
        object.__setattr__(self, "evidence", _texts(self.evidence, "source.evidence"))


PatternProvenance = SourceProvenance


@dataclass(frozen=True, slots=True)
class LicenseDeclaration:
    """License basis and import mode; omission is never treated as permission."""

    source_license: str
    import_mode: ImportMode
    attribution: str

    def __post_init__(self) -> None:
        license_name = self.source_license
        _text(license_name, "license.source_license")
        object.__setattr__(self, "source_license", license_name)
        try:
            mode = self.import_mode if isinstance(self.import_mode, ImportMode) else ImportMode(self.import_mode)
        except (TypeError, ValueError) as exc:
            raise AsolariaPatternContractError(
                "license.import_mode must be reimplementation or permissive"
            ) from exc
        object.__setattr__(self, "import_mode", mode)
        _text(self.attribution, "license.attribution")
        if license_name.casefold() in _NO_LICENSE and mode is not ImportMode.REIMPLEMENTATION:
            raise AsolariaPatternContractError(
                "unlicensed source requires import_mode=reimplementation"
            )


@dataclass(frozen=True, slots=True)
class BenchmarkGate:
    """Reproducible benchmark receipt required before an import is accepted."""

    command: str
    dataset: str
    expected: str
    observed: str
    receipt: str
    passed: bool
    reproducible: bool

    def __post_init__(self) -> None:
        for name in ("command", "dataset", "expected", "observed", "receipt"):
            _text(getattr(self, name), f"benchmark.{name}")
        if self.passed is not True:
            raise AsolariaPatternContractError("benchmark.passed must be true")
        if self.reproducible is not True:
            raise AsolariaPatternContractError("benchmark.reproducible must be true")


@dataclass(frozen=True, slots=True)
class PatternImportManifest:
    """Complete, serializable metadata required by the bounded import gate."""

    identity: PatternIdentity
    source: SourceProvenance
    hypothesis: str
    falsifier: str
    license: LicenseDeclaration
    boundary: str
    scientific_evidence: tuple[str, ...]
    benchmark: BenchmarkGate
    schema: str = SCHEMA
    issue_number: int = ISSUE_NUMBER

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise AsolariaPatternContractError(f"schema must equal {SCHEMA!r}")
        if self.issue_number != ISSUE_NUMBER:
            raise AsolariaPatternContractError(f"issue_number must be {ISSUE_NUMBER}")
        if not isinstance(self.identity, PatternIdentity):
            raise TypeError("identity must be a PatternIdentity")
        if not isinstance(self.source, SourceProvenance):
            raise TypeError("source must be a SourceProvenance")
        if self.source.pattern is not self.identity.name:
            raise AsolariaPatternContractError("source.pattern must match identity.name")
        if not isinstance(self.license, LicenseDeclaration):
            raise TypeError("license must be a LicenseDeclaration")
        if not isinstance(self.benchmark, BenchmarkGate):
            raise TypeError("benchmark must be a BenchmarkGate")
        for name in ("hypothesis", "falsifier", "boundary"):
            _text(getattr(self, name), name)
        object.__setattr__(
            self,
            "scientific_evidence",
            _texts(self.scientific_evidence, "scientific_evidence"),
        )

    @classmethod
    def from_mapping(cls, manifest: Mapping[str, Any]) -> "PatternImportManifest":
        """Build a typed manifest after the same fail-closed validation."""

        result = validate_manifest(manifest)
        result.require_valid()
        identity = manifest["identity"]
        source = manifest["source"]
        license_data = manifest["license"]
        benchmark = manifest["benchmark"]
        assert isinstance(identity, Mapping)
        assert isinstance(source, Mapping)
        assert isinstance(license_data, Mapping)
        assert isinstance(benchmark, Mapping)
        return cls(
            schema=manifest["schema"],
            issue_number=manifest.get("issue_number", ISSUE_NUMBER),
            identity=PatternIdentity(
                PatternName(identity["name"]), identity["version"], identity["summary"]
            ),
            source=SourceProvenance(
                PatternName(source["pattern"]),
                source["repository"],
                source["url"],
                source["path"],
                source["revision"],
                tuple(source["evidence"]),
            ),
            hypothesis=manifest["hypothesis"],
            falsifier=manifest["falsifier"],
            license=LicenseDeclaration(
                license_data["source_license"],
                ImportMode(license_data["import_mode"]),
                license_data["attribution"],
            ),
            boundary=manifest["boundary"],
            scientific_evidence=tuple(manifest["scientific_evidence"]),
            benchmark=BenchmarkGate(
                benchmark["command"],
                benchmark["dataset"],
                benchmark["expected"],
                benchmark["observed"],
                benchmark["receipt"],
                benchmark["passed"],
                benchmark["reproducible"],
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation with stable field names."""

        return {
            "schema": self.schema,
            "issue_number": self.issue_number,
            "identity": {
                "name": self.identity.name.value,
                "version": self.identity.version,
                "summary": self.identity.summary,
            },
            "source": {
                "pattern": self.source.pattern.value,
                "repository": self.source.repository,
                "url": self.source.url,
                "path": self.source.path,
                "revision": self.source.revision,
                "evidence": list(self.source.evidence),
            },
            "hypothesis": self.hypothesis,
            "falsifier": self.falsifier,
            "license": {
                "source_license": self.license.source_license,
                "import_mode": self.license.import_mode.value,
                "attribution": self.license.attribution,
            },
            "boundary": self.boundary,
            "scientific_evidence": list(self.scientific_evidence),
            "benchmark": {
                "command": self.benchmark.command,
                "dataset": self.benchmark.dataset,
                "expected": self.benchmark.expected,
                "observed": self.benchmark.observed,
                "receipt": self.benchmark.receipt,
                "passed": self.benchmark.passed,
                "reproducible": self.benchmark.reproducible,
            },
        }

    def to_json(self) -> str:
        """Serialize the manifest deterministically for a caller-owned receipt."""

        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class PatternGateResult:
    """Evidence-labelled result of evaluating one import manifest."""

    accepted: bool
    errors: tuple[str, ...]
    scope: str = IMPORT_BOUNDARY

    @property
    def valid(self) -> bool:
        return self.accepted

    def require_valid(self) -> None:
        if not self.accepted:
            raise AsolariaPatternContractError(
                "Asolaria pattern import gate failed: " + "; ".join(self.errors)
            )


def _text(value: Any, path: str, *, token: bool = False) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT_LENGTH:
        raise AsolariaPatternContractError(f"{path} must be a bounded non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AsolariaPatternContractError(f"{path} contains control characters")
    if token and not _TOKEN_RE.fullmatch(value):
        raise AsolariaPatternContractError(f"{path} must be a single bounded token")
    return True


def _texts(values: Any, path: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise AsolariaPatternContractError(f"{path} must be a non-empty sequence of strings")
    if not values or len(values) > MAX_ITEMS:
        raise AsolariaPatternContractError(f"{path} must contain 1 to {MAX_ITEMS} items")
    for index, value in enumerate(values):
        _text(value, f"{path}[{index}]")
    return tuple(values)


def _pattern_name(value: Any, path: str) -> PatternName:
    try:
        return value if isinstance(value, PatternName) else PatternName(value)
    except (TypeError, ValueError) as exc:
        raise AsolariaPatternContractError(
            f"{path} must be exactly 'N-Nest' or 'PRISM-COMB'"
        ) from exc


def _revision(value: Any, path: str) -> bool:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
        raise AsolariaPatternContractError(f"{path} must be an immutable git revision")
    return True


def _required(mapping: Mapping[str, Any], name: str, errors: list[str]) -> Any:
    if name not in mapping:
        errors.append(f"missing required field: {name}")
        return None
    return mapping[name]


def _check_text(mapping: Mapping[str, Any], name: str, errors: list[str], *, token: bool = False) -> None:
    value = _required(mapping, name, errors)
    if name in mapping:
        try:
            _text(value, name, token=token)
        except AsolariaPatternContractError as exc:
            errors.append(str(exc))


def _check_identity(value: Any, errors: list[str]) -> str | None:
    if not isinstance(value, Mapping):
        errors.append("identity must be a mapping")
        return None
    _check_text(value, "name", errors)
    _check_text(value, "version", errors, token=True)
    _check_text(value, "summary", errors)
    if "name" in value:
        try:
            return _pattern_name(value["name"], "identity.name").value
        except AsolariaPatternContractError as exc:
            errors.append(str(exc))
    return None


def _check_source(value: Any, identity_name: str | None, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("source must be a mapping with immutable provenance")
        return
    _check_text(value, "pattern", errors)
    if "pattern" in value:
        try:
            source_name = _pattern_name(value["pattern"], "source.pattern").value
            if identity_name is not None and source_name != identity_name:
                errors.append("source.pattern must match identity.name")
        except AsolariaPatternContractError as exc:
            errors.append(str(exc))
    for name in ("repository", "url", "path"):
        _check_text(value, name, errors)
    revision = _required(value, "revision", errors)
    if "revision" in value:
        try:
            _revision(revision, "source.revision")
        except AsolariaPatternContractError as exc:
            errors.append(str(exc))
    if "evidence" not in value:
        errors.append("missing required field: source.evidence")
    else:
        try:
            _texts(value["evidence"], "source.evidence")
        except AsolariaPatternContractError as exc:
            errors.append(str(exc))


def _check_license(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("license must be a mapping with source_license and import_mode")
        return
    for name in ("source_license", "import_mode", "attribution"):
        _check_text(value, name, errors, token=name == "import_mode")
    if "import_mode" in value:
        try:
            mode = ImportMode(value["import_mode"])
        except (TypeError, ValueError):
            errors.append("license.import_mode must be reimplementation or permissive")
        else:
            source_license = str(value.get("source_license", "")).casefold()
            if source_license in _NO_LICENSE and mode is not ImportMode.REIMPLEMENTATION:
                errors.append("unlicensed source requires license.import_mode=reimplementation")


def _check_benchmark(value: Any, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        errors.append("benchmark must be a mapping with a passing reproducible receipt")
        return
    for name in ("command", "dataset", "expected", "observed", "receipt"):
        _check_text(value, name, errors)
    if value.get("passed") is not True:
        errors.append("benchmark.passed must be true")
    if value.get("reproducible") is not True:
        errors.append("benchmark.reproducible must be true")


def validate_manifest(manifest: Any) -> PatternGateResult:
    """Return a fail-closed result without importing or executing a pattern."""

    if not isinstance(manifest, Mapping):
        return PatternGateResult(False, ("manifest must be a mapping",))

    errors: list[str] = []
    schema = _required(manifest, "schema", errors)
    if "schema" in manifest and schema != SCHEMA:
        errors.append(f"schema must equal {SCHEMA!r}")
    issue_number = manifest.get("issue_number", ISSUE_NUMBER)
    if issue_number != ISSUE_NUMBER:
        errors.append(f"issue_number must be {ISSUE_NUMBER}")

    identity_name = _check_identity(_required(manifest, "identity", errors), errors)
    _check_source(_required(manifest, "source", errors), identity_name, errors)
    for name in ("hypothesis", "falsifier", "boundary"):
        _check_text(manifest, name, errors)
    if "scientific_evidence" not in manifest:
        errors.append("missing required field: scientific_evidence")
    else:
        try:
            _texts(manifest["scientific_evidence"], "scientific_evidence")
        except AsolariaPatternContractError as exc:
            errors.append(str(exc))
    _check_license(_required(manifest, "license", errors), errors)
    _check_benchmark(_required(manifest, "benchmark", errors), errors)

    if len(errors) > MAX_ERRORS:
        errors = errors[:MAX_ERRORS] + ["validation error limit exceeded"]
    return PatternGateResult(not errors, tuple(errors))


def assert_valid_manifest(manifest: Any) -> PatternGateResult:
    """Validate a manifest and raise instead of allowing an unsafe import."""

    result = validate_manifest(manifest)
    result.require_valid()
    return result


def check_manifest(manifest: Any) -> bool:
    """Return only the fail-closed acceptance bit for simple callers."""

    return validate_manifest(manifest).accepted


PatternImportGate = PatternImportManifest


__all__ = [
    "AsolariaPatternContractError",
    "BenchmarkGate",
    "CONTRACT_SCHEMA",
    "IMPORT_BOUNDARY",
    "ISSUE_NUMBER",
    "ImportMode",
    "LicenseDeclaration",
    "PatternGateResult",
    "PatternIdentity",
    "PatternImportGate",
    "PatternImportManifest",
    "PatternName",
    "PatternProvenance",
    "SCHEMA",
    "SourceProvenance",
    "assert_valid_manifest",
    "check_manifest",
    "validate_manifest",
]

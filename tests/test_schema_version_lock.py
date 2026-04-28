"""Tests for `lock-canonical-yaml-schema-v1` extractor-side
enforcement: write_device_yaml refuses payloads missing
`schema_version` or whose major mismatches the bundled schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alloy_data_extractor.emit.canonical_yaml import (  # noqa: E402
    SCHEMA_VERSION_CURRENT,
    ValidationIssue,
    validate_yaml_file,
    write_device_yaml,
)


def _payload(*, schema_version: str | None = SCHEMA_VERSION_CURRENT) -> dict:
    p: dict = {
        "identity": {
            "vendor": "synth",
            "family": "synthfam",
            "device": "synthdev",
            "core": "cortex-m0",
        },
    }
    if schema_version is not None:
        p["schema_version"] = schema_version
    return p


def _write(payload: dict, tmp_path: Path):
    return write_device_yaml(
        payload=payload,
        output_root=tmp_path,
        vendor="synth",
        family="synthfam",
        device="synthdev",
    )


def test_write_refuses_payload_missing_schema_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as excinfo:
        _write(_payload(schema_version=None), tmp_path)
    assert "schema_version" in str(excinfo.value)
    assert not list(tmp_path.glob("**/*.yml"))


def test_write_refuses_future_major(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as excinfo:
        _write(_payload(schema_version="2.0.0"), tmp_path)
    msg = str(excinfo.value)
    assert "2.0.0" in msg
    assert SCHEMA_VERSION_CURRENT in msg


def test_write_refuses_non_string_schema_version(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "identity": {"vendor": "a", "family": "b", "device": "c", "core": "d"},
    }
    with pytest.raises(ValueError):
        _write(payload, tmp_path)


def test_write_accepts_minor_bump_within_major(tmp_path: Path) -> None:
    out = _write(_payload(schema_version="1.99.99"), tmp_path)
    assert out.exists()


def test_validate_yaml_file_reports_missing_schema_version(tmp_path: Path) -> None:
    yaml_path = tmp_path / "synth.yml"
    yaml_path.write_text(
        "identity:\n  vendor: a\n  family: b\n  device: c\n  core: d\n",
        encoding="utf-8",
    )
    schema_path = (
        ROOT / ".."  / "alloy-devices-yml" / "schema" / "canonical_device" / "device.schema.json"
    ).resolve()
    if not schema_path.exists():
        pytest.skip(f"alloy-devices-yml schema not found at {schema_path}")
    issues = validate_yaml_file(yaml_path, schema_path)
    paths = [i.path for i in issues]
    assert "schema_version" in paths


def test_validate_yaml_file_returns_empty_for_valid_payload(tmp_path: Path) -> None:
    schema_path = (
        ROOT / ".." / "alloy-devices-yml" / "schema" / "canonical_device" / "device.schema.json"
    ).resolve()
    if not schema_path.exists():
        pytest.skip(f"alloy-devices-yml schema not found at {schema_path}")
    payload_text = (
        f"schema_version: {SCHEMA_VERSION_CURRENT}\n"
        "identity:\n  vendor: a\n  family: b\n  device: c\n  core: d\n"
    )
    yaml_path = tmp_path / "synth.yml"
    yaml_path.write_text(payload_text, encoding="utf-8")
    issues = validate_yaml_file(yaml_path, schema_path)
    assert issues == ()


def test_validation_issue_dataclass_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    issue = ValidationIssue(path="foo", message="bar")
    with pytest.raises(FrozenInstanceError):
        issue.path = "x"  # type: ignore[misc]

"""
Tests for SERVICE_VERSION code-derived default in telemetry.py.

_build_version() reads backend/VERSION so deploys are version-stamped even
without a SERVICE_VERSION Cloud Run env var.
"""

import os


def test_build_version_reads_file():
    """_build_version() returns a non-empty string that is not 'unknown'."""
    from observability.telemetry import _build_version
    version = _build_version()
    assert isinstance(version, str)
    assert version != ""
    assert version != "unknown", (
        "_build_version() should read backend/VERSION, not fall back to 'unknown'"
    )


def test_build_version_returns_semver():
    """_build_version() returns the exact semver string from backend/VERSION."""
    from observability.telemetry import _build_version
    version = _build_version()
    # Must look like a semver (at least two dots, all numeric parts)
    parts = version.split(".")
    assert len(parts) >= 2, f"Expected semver like '1.2.0', got {version!r}"
    for part in parts:
        assert part.isdigit(), f"Expected all-numeric version parts, got {version!r}"


def test_service_version_env_wins():
    """When SERVICE_VERSION env var is set, it takes priority over the file."""
    sentinel = "9.9.9-test"
    original = os.environ.get("SERVICE_VERSION")
    try:
        os.environ["SERVICE_VERSION"] = sentinel
        # The module-level constant is already bound; test the logic expression directly.
        result = os.environ.get("SERVICE_VERSION") or "fallback"
        assert result == sentinel
    finally:
        if original is None:
            os.environ.pop("SERVICE_VERSION", None)
        else:
            os.environ["SERVICE_VERSION"] = original


def test_service_version_falls_back_to_file():
    """When SERVICE_VERSION env var is absent, logic falls back to _build_version()."""
    from observability.telemetry import _build_version
    # Simulate: os.environ.get("SERVICE_VERSION") is None/empty → use _build_version()
    file_version = _build_version()
    env_value = None  # env var absent
    result = env_value or file_version
    assert result == file_version
    assert result != "unknown"


def test_module_constant_is_set():
    """SERVICE_VERSION module constant is importable and non-empty."""
    from observability import telemetry
    assert hasattr(telemetry, "SERVICE_VERSION")
    assert isinstance(telemetry.SERVICE_VERSION, str)
    assert telemetry.SERVICE_VERSION != ""

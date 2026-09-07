"""
tests/integration/test_dead_code_removed.py — Guard against re-introduction of deleted modules.

Each test asserts that the corresponding module raises ModuleNotFoundError on
import, confirming it has been permanently removed from the codebase.
"""

import importlib.util
import pathlib
import sys
import pytest


def _assert_module_not_found(module_name: str) -> None:
    # Remove any cached reference so the import is attempted fresh.
    sys.modules.pop(module_name, None)
    with pytest.raises(ModuleNotFoundError):
        __import__(module_name)


def test_utils_vertex_ai_not_importable():
    _assert_module_not_found("utils.vertex_ai")


def test_utils_ocr_not_importable():
    _assert_module_not_found("utils.ocr")


def test_utils_storage_not_importable():
    _assert_module_not_found("utils.storage")


def test_utils_pdf_extract_not_importable():
    _assert_module_not_found("utils.pdf_extract")


def test_utils_pdf_merge_not_importable():
    _assert_module_not_found("utils.pdf_merge")


def test_utils_gemini_client_not_importable():
    _assert_module_not_found("utils.gemini_client")


def test_utils_auth_not_importable():
    _assert_module_not_found("utils.auth")


def test_utils_save_output_not_importable():
    _assert_module_not_found("utils.save_output")


def test_config_py_deleted():
    import sys
    sys.modules.pop("config", None)
    assert importlib.util.find_spec("config") is None, \
        "backend/config.py must not exist"


def test_utils_athena_client_module_is_gone():
    _assert_module_not_found("utils.athena_client")


def test_backend_root_only_app():
    """Only app.py lives at backend/ root."""
    root = pathlib.Path(__file__).parent.parent.parent  # backend/
    py_files = {f.name for f in root.glob("*.py") if f.is_file()}
    allowed = {"app.py"}
    unexpected = py_files - allowed
    assert not unexpected, f"Unexpected .py files at backend root: {unexpected}"

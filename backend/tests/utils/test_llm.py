"""
tests/utils/test_llm.py — Tests for utils/llm.py (LLMClient).

Covers (Vertex AI path only — AI Studio path removed for HIPAA compliance):
  1. Vertex AI initialisation: vertexai.init called, GenerativeModel instantiated
  2. Safety settings applied with all four HarmCategory keys set to BLOCK_NONE
  3. generate_text: returns stripped text, logs warning on MAX_TOKENS, raises on no candidates
  4. generate_json: fenced JSON, raw JSON, list, invalid JSON raises ValueError
"""

import json
import sys
import os
import contextlib
import logging
from unittest.mock import MagicMock, patch

import pytest

from errors import ErrorCode, SimplifyError


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vertex_env():
    """Set up Vertex AI mocks and ensure GEMINI_API_KEY is absent."""
    mock_vertexai = MagicMock()
    mock_GenerativeModel = MagicMock()
    mock_HarmBlockThreshold = MagicMock()
    mock_HarmCategory = MagicMock()
    mock_FinishReason = MagicMock()
    mock_GenerationConfig = MagicMock()

    hc = mock_HarmCategory
    hc.HARM_CATEGORY_HATE_SPEECH = "hate"
    hc.HARM_CATEGORY_DANGEROUS_CONTENT = "dangerous"
    hc.HARM_CATEGORY_SEXUALLY_EXPLICIT = "sexual"
    hc.HARM_CATEGORY_HARASSMENT = "harassment"
    mock_HarmBlockThreshold.BLOCK_NONE = "BLOCK_NONE"

    mock_Part = MagicMock()

    mock_preview_models = MagicMock()
    mock_preview_models.GenerativeModel = mock_GenerativeModel
    mock_preview_models.HarmBlockThreshold = mock_HarmBlockThreshold
    mock_preview_models.HarmCategory = mock_HarmCategory
    mock_preview_models.FinishReason = mock_FinishReason
    mock_preview_models.GenerationConfig = mock_GenerationConfig
    mock_preview_models.Part = mock_Part

    # Ensure the non-compliant key is never present during tests
    env_override = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}

    with patch.dict("os.environ", env_override, clear=True), \
         patch.dict("sys.modules", {
             "vertexai": mock_vertexai,
             "vertexai.preview": MagicMock(),
             "vertexai.preview.generative_models": mock_preview_models,
         }):
        # Ensure utils.llm is re-imported fresh so it binds to the mocked vertexai.
        sys.modules.pop("utils.llm", None)
        yield mock_vertexai, mock_GenerativeModel, mock_HarmBlockThreshold, mock_HarmCategory, mock_FinishReason, mock_preview_models, mock_Part

    sys.modules.pop("utils.llm", None)


@contextlib.contextmanager
def _capture_logs(logger_name, level):
    """Capture log messages from the named logger."""
    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = _Handler()
    handler.setLevel(getattr(logging, level))
    log = logging.getLogger(logger_name)
    orig_level = log.level
    log.setLevel(getattr(logging, level))
    log.addHandler(handler)
    try:
        yield records
    finally:
        log.removeHandler(handler)
        log.setLevel(orig_level)


# ---------------------------------------------------------------------------
# Initialisation tests
# ---------------------------------------------------------------------------

def test_inits_vertexai(vertex_env):
    mock_vertexai, *_ = vertex_env
    from utils.llm import LLMClient
    LLMClient()
    mock_vertexai.init.assert_called_once()


def test_safety_settings_applied(vertex_env):
    """_safety dict must have all 4 HarmCategory keys set to BLOCK_NONE."""
    from utils.llm import LLMClient
    client = LLMClient()
    assert isinstance(client._safety, dict)
    assert len(client._safety) == 4
    for v in client._safety.values():
        assert v == "BLOCK_NONE"


# ---------------------------------------------------------------------------
# generate_text tests
# ---------------------------------------------------------------------------

def test_generate_text_returns_stripped_text(vertex_env):
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "OTHER"
    mock_FinishReason.MAX_TOKENS = "MAX_TOKENS"

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = "  vertex output  "
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    result = client.generate_text("test prompt")

    assert result == "vertex output"


def test_generate_text_passes_safety_settings(vertex_env):
    """generate_text must always pass safety_settings to generate_content."""
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_response = MagicMock()
    mock_response.candidates = [MagicMock()]
    mock_response.text = "output"
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    client.generate_text("prompt")

    call_kwargs = mock_model_instance.generate_content.call_args[1]
    assert "safety_settings" in call_kwargs
    assert call_kwargs["safety_settings"] == client._safety


def test_generate_text_max_tokens_logs_warning(vertex_env):
    """When finish_reason == MAX_TOKENS, raise SimplifyError with LLM_MAX_TOKENS code."""
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_candidate = MagicMock()
    mock_FinishReason.MAX_TOKENS = "MAX_TOKENS"
    mock_candidate.finish_reason = "MAX_TOKENS"

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = "  partial output  "
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()

    with pytest.raises(SimplifyError) as exc_info:
        client.generate_text("test prompt")

    assert exc_info.value.error_code == ErrorCode.LLM_MAX_TOKENS


def test_generate_text_max_tokens_detail_records_max_tokens_value(vertex_env):
    """Regression: the detail must record which max_tokens value was in effect
    so a MAX_TOKENS failure is diagnosable from logs (which call site, what
    budget) without guessing."""
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_candidate = MagicMock()
    mock_FinishReason.MAX_TOKENS = "MAX_TOKENS"
    mock_candidate.finish_reason = "MAX_TOKENS"

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = "partial output"
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()

    with pytest.raises(SimplifyError) as exc_info:
        client.generate_text("test prompt", max_tokens=65536)

    assert "max_tokens=65536" in exc_info.value.detail


def test_generate_text_no_candidates_raises(vertex_env):
    mock_vertexai, mock_GenerativeModel, *_ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_response = MagicMock()
    mock_response.candidates = []
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    with pytest.raises(SimplifyError) as exc_info:
        client.generate_text("test prompt")
    assert exc_info.value.error_code == ErrorCode.LLM_NO_CANDIDATES


def test_generate_text_vertex_failure_raises_vertex_api_error(vertex_env):
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    from google.api_core import exceptions as gexc
    mock_model_instance.generate_content.side_effect = gexc.ResourceExhausted("quota exceeded")

    from errors import ErrorCode, VertexAPIError
    from utils.llm import LLMClient
    client = LLMClient()
    with pytest.raises(VertexAPIError) as exc_info:
        client.generate_text("prompt")
    assert exc_info.value.error_code == ErrorCode.VERTEX_QUOTA_EXCEEDED


def test_generate_text_still_works_after_refactor(vertex_env):
    """Regression: the _generate_content extraction must not change the
    text-only path (copy of test_generate_text_returns_stripped_text)."""
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "OTHER"
    mock_FinishReason.MAX_TOKENS = "MAX_TOKENS"

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = "  vertex output  "
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    result = client.generate_text("test prompt")

    assert result == "vertex output"


# ---------------------------------------------------------------------------
# generate_text_from_image tests
# ---------------------------------------------------------------------------

def test_generate_text_from_image_calls_generate_content_with_part_and_prompt(vertex_env):
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, mock_Part = vertex_env
    mock_Part.from_data.return_value = "the-part-object"

    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "OTHER"
    mock_FinishReason.MAX_TOKENS = "MAX_TOKENS"

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = "  extracted  "
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    result = client.generate_text_from_image(b"imgbytes", "image/png", "prompt text")

    mock_Part.from_data.assert_called_once_with(data=b"imgbytes", mime_type="image/png")
    assert mock_model_instance.generate_content.call_args[0][0] == ["the-part-object", "prompt text"]
    assert result == "extracted"


def test_generate_text_from_image_max_tokens_raises(vertex_env):
    """Shares response handling: MAX_TOKENS scenario via generate_text_from_image."""
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, mock_Part = vertex_env
    mock_Part.from_data.return_value = MagicMock()
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_candidate = MagicMock()
    mock_FinishReason.MAX_TOKENS = "MAX_TOKENS"
    mock_candidate.finish_reason = "MAX_TOKENS"

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = "  partial output  "
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()

    with pytest.raises(SimplifyError) as exc_info:
        client.generate_text_from_image(b"x", "image/png", "p")

    assert exc_info.value.error_code == ErrorCode.LLM_MAX_TOKENS


def test_generate_text_from_image_no_candidates_raises(vertex_env):
    """Shares response handling: no-candidates scenario via generate_text_from_image."""
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, mock_Part = vertex_env
    mock_Part.from_data.return_value = MagicMock()
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_response = MagicMock()
    mock_response.candidates = []
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    with pytest.raises(SimplifyError) as exc_info:
        client.generate_text_from_image(b"x", "image/png", "p")
    assert exc_info.value.error_code == ErrorCode.LLM_NO_CANDIDATES


def test_generate_text_from_image_vertex_failure_raises_vertex_api_error(vertex_env):
    """Shares response handling: Vertex API failure scenario via generate_text_from_image."""
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, mock_Part = vertex_env
    mock_Part.from_data.return_value = MagicMock()
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    from google.api_core import exceptions as gexc
    mock_model_instance.generate_content.side_effect = gexc.ResourceExhausted("quota exceeded")

    from errors import ErrorCode, VertexAPIError
    from utils.llm import LLMClient
    client = LLMClient()
    with pytest.raises(VertexAPIError) as exc_info:
        client.generate_text_from_image(b"x", "image/png", "p")
    assert exc_info.value.error_code == ErrorCode.VERTEX_QUOTA_EXCEEDED


# ---------------------------------------------------------------------------
# generate_json tests
# ---------------------------------------------------------------------------

def test_generate_json_fenced_block(vertex_env):
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    payload = {"key": "value", "num": 42}
    mock_response = MagicMock()
    mock_response.candidates = [MagicMock()]
    mock_response.text = f"```json\n{json.dumps(payload)}\n```"
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    result = client.generate_json("prompt")
    assert result == payload


def test_generate_json_raw_json(vertex_env):
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    payload = {"a": 1}
    mock_response = MagicMock()
    mock_response.candidates = [MagicMock()]
    mock_response.text = json.dumps(payload)
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    result = client.generate_json("prompt")
    assert result == payload


def test_generate_json_returns_list(vertex_env):
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    payload = [1, 2, 3]
    mock_response = MagicMock()
    mock_response.candidates = [MagicMock()]
    mock_response.text = json.dumps(payload)
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    result = client.generate_json("prompt")
    assert result == payload


def test_generate_json_invalid_raises_value_error(vertex_env):
    mock_vertexai, mock_GenerativeModel, _, _, mock_FinishReason, _, _ = vertex_env
    mock_model_instance = MagicMock()
    mock_GenerativeModel.return_value = mock_model_instance

    mock_response = MagicMock()
    mock_response.candidates = [MagicMock()]
    mock_response.text = "not valid json {{{"
    mock_model_instance.generate_content.return_value = mock_response

    from utils.llm import LLMClient
    client = LLMClient()
    with pytest.raises(SimplifyError) as exc_info:
        client.generate_json("prompt")
    assert exc_info.value.error_code == ErrorCode.LLM_INVALID_JSON

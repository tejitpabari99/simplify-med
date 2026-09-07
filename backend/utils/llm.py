"""
utils/llm.py — LLM client for Vertex AI (HIPAA-compliant path only).

Uses vertexai SDK exclusively. Google AI Studio (google-generativeai /
GEMINI_API_KEY) is not used because it is excluded from Google's HIPAA BAA.

Requires environment variables:
  GCP_PROJECT_ID  — GCP project that has Vertex AI API enabled
  GCP_LOCATION    — region (default: us-central1)
  VERTEX_AI_MODEL — model name (default: gemini-1.5-pro)
"""

import json
import logging
import os
import re

import vertexai
from vertexai.preview.generative_models import (
    FinishReason,
    GenerationConfig as VertexGenerationConfig,
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    Part,
)

from errors import ErrorCode, SimplifyError, VertexAPIError, classify_finish_reason
from utils.constants import Constants

logger = logging.getLogger(__name__)


def _strip_json_fences(raw: str) -> str:
    # Accept both raw JSON and markdown-fenced JSON from model outputs.
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    return match.group(1).strip() if match else raw.strip()


class LLMClient:
    """LLM client backed exclusively by Vertex AI."""

    def __init__(self, model_name: str | None = None):
        if model_name is None:
            model_name = os.environ.get(Constants.EnvVars.VERTEX_AI_MODEL, Constants.Llm.MODEL_DEFAULT)

        project_id = os.environ.get("GCP_PROJECT_ID", "")
        location = os.environ.get("GCP_LOCATION", "us-central1")
        vertexai.init(project=project_id, location=location)
        self._model = GenerativeModel(model_name)
        self._safety = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        }
        self._FinishReason = FinishReason
        self._VertexGenerationConfig = VertexGenerationConfig
        logger.info("LLMClient: using Vertex AI")

    def _generate_content(self, contents, temperature: float, max_tokens: int) -> str:
        """Shared Vertex call + response handling for both text-only and
        multimodal (image + prompt) generation. `contents` is passed straight
        through to GenerativeModel.generate_content, which accepts a bare str
        or a list of [Part, str, ...]."""
        try:
            response = self._model.generate_content(
                contents,
                generation_config=self._VertexGenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
                safety_settings=self._safety,
            )
        except Exception as api_exc:
            # Classify google.api_core exceptions via VertexAPIError; re-raise others as UNKNOWN_ERROR
            try:
                from google.api_core import exceptions as _gexc
                if isinstance(api_exc, _gexc.GoogleAPICallError):
                    raise VertexAPIError(api_exc) from api_exc
            except ImportError:
                pass
            raise SimplifyError(
                ErrorCode.UNKNOWN_ERROR,
                detail=f"Vertex AI generate_content raised an unexpected error: {api_exc}",
                original=api_exc,
            ) from api_exc

        if not response.candidates:
            raise SimplifyError(
                ErrorCode.LLM_NO_CANDIDATES,
                detail="Model response contained no candidates; generation may have been fully blocked.",
            )

        candidate = response.candidates[0]
        if hasattr(candidate, "finish_reason") and candidate.finish_reason == self._FinishReason.MAX_TOKENS:
            raise SimplifyError(
                ErrorCode.LLM_MAX_TOKENS,
                detail=(
                    f"LLM generation hit the output token limit before completing "
                    f"(max_tokens={max_tokens} was in effect for this call). "
                    f"This is an output-cap failure, not an input-length one -- "
                    f"consider raising max_tokens for this call site. "
                    f"finish_reason={candidate.finish_reason!r}"
                ),
            )

        if not getattr(candidate, "content", None) or not getattr(candidate.content, "parts", None):
            finish_reason = getattr(candidate, "finish_reason", None)
            finish_reason_name = finish_reason.name if finish_reason is not None else "OTHER"
            error_code = classify_finish_reason(finish_reason_name)
            raise SimplifyError(
                error_code,
                detail=(
                    f"LLM response candidate has no content parts. "
                    f"finish_reason={finish_reason!r}"
                ),
            )

        return response.text.strip()

    def generate_text(self, prompt: str, temperature: float = Constants.Llm.TEMPERATURE_TEXT, max_tokens: int = Constants.Llm.MAX_TOKENS) -> str:
        """Generate text from a prompt. Returns the text string directly."""
        return self._generate_content(prompt, temperature, max_tokens)

    def generate_text_from_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        temperature: float = Constants.Llm.TEMPERATURE_TEXT,
        max_tokens: int = Constants.Llm.MAX_TOKENS,
    ) -> str:
        """Generate text from an image + instruction prompt (Gemini vision).
        Shares all response/error handling with generate_text via _generate_content."""
        part = Part.from_data(data=image_bytes, mime_type=mime_type)
        return self._generate_content([part, prompt], temperature, max_tokens)

    def generate_json(self, prompt: str, temperature: float = Constants.Llm.TEMPERATURE_JSON, max_tokens: int = Constants.Llm.MAX_TOKENS) -> dict | list:
        """Generate JSON from a prompt. Strips markdown fences and parses JSON."""
        raw = self.generate_text(prompt, temperature, max_tokens)
        try:
            return json.loads(_strip_json_fences(raw))
        except json.JSONDecodeError as e:
            raise SimplifyError(
                ErrorCode.LLM_INVALID_JSON,
                detail=f"LLM returned invalid JSON: {e}. Raw start: {raw[:200]!r}",
                original=e,
            ) from e

"""Pure, stateless helpers for translating between JobDoc and Metrics shapes."""

_INPUT_TYPE_MAP = {
    "upload": "file",
    "text": "text",
}


def canonical_input_type(source_kind: str) -> str:
    return _INPUT_TYPE_MAP.get(source_kind, "text")

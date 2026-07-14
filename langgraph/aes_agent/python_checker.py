from __future__ import annotations

import ast
import re
from typing import Any, Dict, List


CODE_FIELD_CANDIDATES = (
    "python_code",
    "code",
    "script",
    "solve_py",
    "file_content",
    "content",
)


def python_code_from_model_result(model_result: Dict[str, Any]) -> str:
    """
    Extract the most likely Python source from a model JSON response.

    LLMs do not always obey the exact `python_code` key. This helper accepts a
    small set of common aliases and a simple `files` shape, then normalizes the
    extracted source before the safety checker sees it.
    """
    for key in CODE_FIELD_CANDIDATES:
        value = model_result.get(key)
        if isinstance(value, str):
            code = extract_python_code(value)
            if code:
                return code

    files = model_result.get("files")
    if isinstance(files, list):
        for item in files:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("filename") or "")
            if name and not name.endswith(".py"):
                continue
            content = item.get("content") or item.get("code")
            if isinstance(content, str):
                code = extract_python_code(content)
                if code:
                    return code

    return ""


def extract_python_code(value: str) -> str:
    """
    Normalize a string that may contain plain Python, a fenced code block, or a
    small amount of prose around the code.
    """
    stripped = strip_invalid_python_control_chars(value).strip()
    if not stripped:
        return ""

    fenced = _first_fenced_python_block(stripped)
    if fenced:
        return fenced

    if _looks_like_python_source(stripped):
        return stripped

    return ""


def check_python_syntax(code: str) -> Dict[str, Any]:
    if not code.strip():
        return {
            "status": "invalid",
            "errors": ["Python code is empty."],
            "warnings": [],
            "tree": None,
        }

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {
            "status": "invalid",
            "errors": [f"Generated Python code has a syntax error: {exc}"],
            "warnings": [],
            "tree": None,
        }

    return {
        "status": "valid",
        "errors": [],
        "warnings": [],
        "tree": tree,
    }


def strip_invalid_python_control_chars(value: str) -> str:
    value = value.replace("\u00a0", " ")
    return "".join(
        char
        for char in value
        if char in {"\n", "\r", "\t"} or (ord(char) >= 32 and ord(char) != 127)
    )


def _first_fenced_python_block(value: str) -> str:
    patterns = (
        r"```(?:python|py)\s*(.*?)```",
        r"```\s*(.*?)```",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE | re.DOTALL)
        if match:
            candidate = strip_invalid_python_control_chars(match.group(1)).strip()
            if _looks_like_python_source(candidate):
                return candidate
    return ""


def _looks_like_python_source(value: str) -> bool:
    lowered = value.lower()
    markers = (
        "from ",
        "import ",
        "def ",
        "class ",
        "print(",
        "ufl.",
        "dolfinx",
        "fem.",
        "mesh.",
        "petsc",
    )
    return any(marker in lowered for marker in markers)

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class InitialConditionClause:
    expression: str
    scope: str
    start: int
    end: int


def _clause_end(text: str, start: int) -> int:
    end = start
    depth = 0
    # Commas in coordinates/functions and decimal points are not clause boundaries.
    while end < len(text):
        char = text[end]
        if depth == 0 and (
            char in ",;\n"
            or (char == "." and not (end + 1 < len(text) and text[end + 1].isdigit()))
        ):
            break
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        end += 1
    following = re.search(
        r"\s+(?:and|with)\s+(?:use\s+)?"
        r"(?:final|initial|time|dt\b|T\s*=|alpha\b|[afkgu]\s*=|execute|store|boundary)",
        text[start:end], re.IGNORECASE,
    )
    return start + following.start() if following else end


def explicit_parameter_expression(text: str, names: tuple[str, ...]) -> str:
    names_pattern = "|".join(re.escape(name) for name in names)
    pattern = rf"\b(?:{names_pattern})(?:\s*\([^)]*\))?\s*(?:=|is)\s*"
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    if not matches:
        return ""
    match = matches[-1]
    return text[match.end():_clause_end(text, match.end())].strip().strip("`$ ")


def initial_condition_clauses(text: str) -> list[InitialConditionClause]:
    """Separate initial-field expressions from spatial qualifiers without losing either."""
    assignment = re.compile(
        r"\b(?:initial\s+(?:condition|temperature)\s*"
        r"(?:u(?:\s*\([^)]*\))?)?|u\s*\([^)]*,\s*0\s*\)|u_?0)"
        r"\s*(?:=|is)\s*",
        re.IGNORECASE,
    )
    clauses: list[InitialConditionClause] = []
    for match in assignment.finditer(text):
        end = _clause_end(text, match.end())
        body = text[match.end():end]
        parts = re.split(r"\s+(?:on|in|throughout)\s+", body, maxsplit=1, flags=re.IGNORECASE)
        clauses.append(InitialConditionClause(
            expression=parts[0].strip().strip("`$ "),
            scope=parts[1].strip() if len(parts) > 1 else "",
            start=match.start(),
            end=end,
        ))
    return clauses


def without_initial_conditions(text: str) -> str:
    """Keep transient initial assignments out of the boundary-condition parser."""
    for clause in reversed(initial_condition_clauses(text)):
        text = text[:clause.start] + " " * (clause.end - clause.start) + text[clause.end:]
    return text

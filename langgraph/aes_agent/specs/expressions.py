from __future__ import annotations

from typing import Literal

from pydantic import Field

from aes_agent.specs.base import StrictModel


class ExpressionSpec(StrictModel):
    kind: Literal["constant", "symbolic"]
    value: str = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)


def expression_from_text(value: str, *, variables: list[str] | None = None) -> ExpressionSpec:
    normalized = str(value).strip()
    try:
        float(normalized)
        kind = "constant"
    except ValueError:
        kind = "symbolic"
    return ExpressionSpec(
        kind=kind,
        value=normalized or "0",
        variables=list(variables or []),
    )

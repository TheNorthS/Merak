"""Version-1 evaluation declarations shared by authors, design gates and publication."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvaluationDeclaration(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    protocol_schema: Literal[1] = 1
    holdout_axes: list[str] = Field(default_factory=list)
    primary_split: str = ""
    primary_metric: str = ""
    analysis_unit: str = ""
    analysis_unit_key: str = ""

    @field_validator("holdout_axes")
    @classmethod
    def named_unique_axes(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values) or len(set(values)) != len(values):
            raise ValueError("holdout_axes must contain unique nonempty names")
        return values


def evaluation_authoring_contract() -> str:
    return (
        "Evaluation protocol v1: evaluation.protocol_schema=1; holdout_axes is a list[str], "
        "for example [subject, site, montage], never a mapping. Put axis manifests in "
        "data.split_manifests (axis -> path). Declare evaluation.primary_split as the complete "
        "scientific evaluation scope, primary_metric as the measured endpoint, and analysis_unit_key. "
        "data.active_holdout_axis selects execution only and never replaces the primary scientific scope. "
        "If RUN_SPEC repeats these fields, all declarations must agree. Preserve independent axes."
    )


def declaration_issues(value: object) -> list[str]:
    if value is None:
        return []
    try:
        EvaluationDeclaration.model_validate(value)
    except ValueError as error:
        return [f"Evaluation protocol v1: {error}"]
    return []

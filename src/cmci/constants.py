"""Governance vocabulary shared by the CMCI data infrastructure."""

from __future__ import annotations

from enum import StrEnum


class Layer(StrEnum):
    """Fixed research architecture layers (charter section 2)."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class IndicatorStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DISABLED = "disabled"


class SourceStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    DISABLED = "disabled"


class SourceRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class SourceType(StrEnum):
    API = "api"
    PUBLIC_DATASET = "public_dataset"
    COMMERCIAL_API = "commercial_api"
    FILE = "file"
    MANUAL = "manual"


class UpdateMethod(StrEnum):
    API = "api"
    FILE = "file"
    MANUAL = "manual"


INDICATOR_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    IndicatorStatus.CANDIDATE.value: frozenset(
        {IndicatorStatus.ACTIVE.value, IndicatorStatus.DISABLED.value}
    ),
    IndicatorStatus.ACTIVE.value: frozenset({IndicatorStatus.DISABLED.value}),
    IndicatorStatus.DISABLED.value: frozenset({IndicatorStatus.ACTIVE.value}),
}

SOURCE_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    SourceStatus.PENDING_REVIEW.value: frozenset(
        {SourceStatus.ACTIVE.value, SourceStatus.DISABLED.value}
    ),
    SourceStatus.ACTIVE.value: frozenset({SourceStatus.DISABLED.value}),
    SourceStatus.DISABLED.value: frozenset({SourceStatus.ACTIVE.value}),
}
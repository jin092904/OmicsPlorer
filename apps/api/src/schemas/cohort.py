"""Cohort & experiment design API schemas — `GET /datasets/{id}/cohort`.

samples 분포 + cohort_design 을 한 응답으로.
"""
from __future__ import annotations

from pydantic import BaseModel


class SexDistribution(BaseModel):
    male: int
    female: int
    unknown: int


class AgeBucket(BaseModel):
    lo: float
    hi: float
    count: int


class AgeSummary(BaseModel):
    unit: str | None
    min: float | None
    max: float | None
    median: float | None
    buckets: list[AgeBucket]


class LabelCount(BaseModel):
    label: str
    count: int


class SamplesSummary(BaseModel):
    n_total: int
    sex: SexDistribution
    age: AgeSummary
    disease_state: list[LabelCount]
    treatment: list[LabelCount]


class CohortGroup(BaseModel):
    label: str
    role: str  # 'case' | 'control' | 'treatment' | 'comparison' | 'other'
    n: int | None
    criteria: str


class CohortDesign(BaseModel):
    groups: list[CohortGroup]
    design_type: str  # 'case_control' | 'cohort' | ...
    notes: str | None = None


class CohortView(BaseModel):
    samples: SamplesSummary
    design: CohortDesign | None
    design_version: str | None

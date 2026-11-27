"""Pydantic response models for the M8 dashboard API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ComparisonRow(BaseModel):
    player_id: int
    player_name: str
    game_id: str
    game_date: date
    prop_type: str
    line: float
    model_version: str
    model_p: float
    market_mid: float | None
    gap: float | None = Field(description="model_p minus market_mid when mid is present; else null")
    low_confidence: bool
    mean: float
    std: float


class ComparisonsTodayResponse(BaseModel):
    date: date
    as_of: datetime
    count: int
    rows: list[ComparisonRow]


class DensityPoint(BaseModel):
    x: float
    density: float


class ShapItem(BaseModel):
    feature: str
    shap: float


class InjuryItem(BaseModel):
    injury_signal_id: int
    claim_type: str
    severity: str | None
    confidence: float
    source: str
    event_time: datetime
    player_name_raw: str
    raw_text: str


class PlayerDetailResponse(BaseModel):
    player_id: int
    player_name: str
    game_id: str | None
    game_date: date | None
    prop_type: str
    model_version: str | None
    mean: float | None
    std: float | None
    quantile_10: float | None
    quantile_50: float | None
    quantile_90: float | None
    low_confidence: bool | None
    distribution: str | None
    density: list[DensityPoint]
    market_line: float | None
    market_mid: float | None
    model_p: float | None
    gap: float | None
    shap_top5: list[ShapItem]
    injuries: list[InjuryItem]
    comparisons: list[ComparisonRow]


class CalibrationBinRow(BaseModel):
    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    realized_rate: float | None


class PropCalibration(BaseModel):
    prop_type: str
    model_version: str
    brier: float | None
    residual_brier: float | None
    n_contracts: int | None
    source: str


class CalibrationSummaryResponse(BaseModel):
    title: str
    source_files: list[str]
    bins: list[CalibrationBinRow]
    calibration_error: float | None
    brier: float | None
    n_contracts: int | None
    disagreement_note: str | None
    props: list[PropCalibration]
    raw_notes: list[str]


class TableFreshness(BaseModel):
    table: str
    max_available_at: datetime | None
    max_ingested_at: datetime | None
    row_count: int | None


class StatusResponse(BaseModel):
    scheduler_enabled: bool
    job_ids: list[str]
    freshness: list[TableFreshness]
    api_version: str


class AvailableDatesResponse(BaseModel):
    dates: list[date]

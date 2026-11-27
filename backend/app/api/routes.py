"""M8 dashboard HTTP routes."""

from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlmodel import Session, select

from app.api.comparisons import (
    build_comparisons_for_date,
    default_comparison_date,
    density_curve,
    list_comparison_dates,
    slate_as_of,
)
from app.api.schemas import (
    AvailableDatesResponse,
    CalibrationBinRow,
    CalibrationSummaryResponse,
    ComparisonRow,
    ComparisonsTodayResponse,
    DensityPoint,
    InjuryItem,
    PlayerDetailResponse,
    PropCalibration,
    ShapItem,
    StatusResponse,
    TableFreshness,
)
from app.api.versions import prefer_version
from app.backtest.metrics import probability_at_least
from app.backtest.quotes import latest_yes_mid
from app.db.engine import get_session
from app.db.queries import query_injury_signals
from app.db.tables import (
    Game,
    InjurySignal,
    Market,
    MarketSnapshot,
    Player,
    PlayerGameLog,
    Prediction,
)
from app.paths import find_repo_root
from app.scheduler import make_scheduler

router = APIRouter(prefix="/api")

_REPO_ROOT = find_repo_root()
_RESULTS = _REPO_ROOT / "docs" / "results"


@router.get("/comparisons/dates", response_model=AvailableDatesResponse)
def comparison_dates(
    session: Session = Depends(get_session),
) -> AvailableDatesResponse:
    return AvailableDatesResponse(dates=list_comparison_dates(session))


@router.get("/comparisons/today", response_model=ComparisonsTodayResponse)
def comparisons_today(
    date_value: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> ComparisonsTodayResponse:
    chosen = date_value or default_comparison_date(session)
    if chosen is None:
        today = datetime.now(UTC).date()
        return ComparisonsTodayResponse(
            date=today,
            as_of=slate_as_of(today),
            count=0,
            rows=[],
        )
    rows = build_comparisons_for_date(session, game_date=chosen, limit=limit)
    return ComparisonsTodayResponse(
        date=chosen,
        as_of=slate_as_of(chosen),
        count=len(rows),
        rows=rows,
    )


@router.get("/players/{player_id}/detail", response_model=PlayerDetailResponse)
def player_detail(
    player_id: int,
    game_id: str | None = None,
    prop_type: str = Query(default="points"),
    session: Session = Depends(get_session),
) -> PlayerDetailResponse:
    player = session.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="player not found")

    if game_id is None:
        pred_row = session.exec(
            select(Prediction)
            .where(Prediction.player_id == player_id, Prediction.prop_type == prop_type)
            .order_by(desc(Prediction.prediction_time))  # type: ignore[arg-type]
        ).first()
        game_id = pred_row.game_id if pred_row is not None else None

    game: Game | None = session.get(Game, game_id) if game_id else None
    as_of = slate_as_of(game.game_date) if game else datetime.now(UTC)

    pred: Prediction | None = None
    if game_id is not None:
        versions = {
            p.model_version: p
            for p in session.exec(
                select(Prediction).where(
                    Prediction.player_id == player_id,
                    Prediction.game_id == game_id,
                    Prediction.prop_type == prop_type,
                )
            ).all()
        }
        pick = prefer_version(set(versions))
        pred = versions.get(pick) if pick else None

    density: list[DensityPoint] = []
    shap: list[ShapItem] = []
    distribution: str | None = None
    market_line: float | None = None
    market_mid: float | None = None
    model_p: float | None = None
    gap: float | None = None

    if pred is not None:
        distribution = str((pred.payload or {}).get("distribution") or "stored-normal")
        density = [
            DensityPoint(x=p["x"], density=p["density"]) for p in density_curve(pred.mean, pred.std)
        ]
        raw_shap = (pred.payload or {}).get("shap_top5") or []
        if isinstance(raw_shap, list):
            for item in raw_shap:
                if not isinstance(item, dict):
                    continue
                feature = item.get("feature")
                value = item.get("shap")
                if feature is None or value is None:
                    continue
                shap.append(ShapItem(feature=str(feature), shap=float(value)))

        markets = session.exec(
            select(Market).where(
                Market.player_id == player_id,
                Market.game_id == game_id,
                Market.prop_type == prop_type,
            )
        ).all()
        if markets:
            # Use the line closest to the mean for the chart marker.
            market = min(markets, key=lambda m: abs(m.line - pred.mean))
            market_line = market.line
            try:
                model_p = probability_at_least(pred.mean, pred.std, market.line)
            except ValueError:
                model_p = None
            market_mid = latest_yes_mid(session, market.ticker, as_of)
            if market_mid is None:
                market_mid = latest_yes_mid(session, market.ticker, datetime.now(UTC))
            if model_p is not None and market_mid is not None:
                gap = model_p - market_mid

    injuries_raw = query_injury_signals(
        as_of=as_of,
        session=session,
        player_id=player_id,
        limit=20,
    )
    # Also include unresolved-name matches is out of scope; player_id only.
    injuries = [
        InjuryItem(
            injury_signal_id=i.injury_signal_id or 0,
            claim_type=i.claim_type,
            severity=i.severity,
            confidence=i.confidence,
            source=i.source,
            event_time=i.event_time,
            player_name_raw=i.player_name_raw,
            raw_text=i.raw_text,
        )
        for i in injuries_raw
    ]

    comparisons: list[ComparisonRow] = []
    if game is not None:
        comparisons = [
            row
            for row in build_comparisons_for_date(session, game_date=game.game_date, limit=200)
            if row.player_id == player_id
        ]

    return PlayerDetailResponse(
        player_id=player_id,
        player_name=player.current_name,
        game_id=game_id,
        game_date=game.game_date if game else None,
        prop_type=prop_type,
        model_version=pred.model_version if pred else None,
        mean=pred.mean if pred else None,
        std=pred.std if pred else None,
        quantile_10=pred.quantile_10 if pred else None,
        quantile_50=pred.quantile_50 if pred else None,
        quantile_90=pred.quantile_90 if pred else None,
        low_confidence=pred.low_confidence if pred else None,
        distribution=distribution,
        density=density,
        market_line=market_line,
        market_mid=market_mid,
        model_p=model_p,
        gap=gap,
        shap_top5=shap,
        injuries=injuries,
        comparisons=comparisons,
    )


def _parse_m4_bins(text: str) -> list[CalibrationBinRow]:
    bins: list[CalibrationBinRow] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if "bin" in line.lower() and "mean predicted" in line.lower():
            continue
        if line.startswith("| ---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 4:
            continue
        range_part = parts[0]
        m = re.match(r"([0-9.]+)\s+to\s+([0-9.]+)", range_part)
        if not m:
            continue
        try:
            count = int(parts[1])
            mean_p = float(parts[2]) if parts[2] not in {"", "—", "-"} else None
            realized = float(parts[3]) if parts[3] not in {"", "—", "-"} else None
        except ValueError:
            continue
        bins.append(
            CalibrationBinRow(
                lower=float(m.group(1)),
                upper=float(m.group(2)),
                count=count,
                mean_predicted=mean_p,
                realized_rate=realized,
            )
        )
    return bins


def _first_float(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _first_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


@router.get("/calibration/summary", response_model=CalibrationSummaryResponse)
def calibration_summary() -> CalibrationSummaryResponse:
    """Serve precomputed calibration from docs/results (no live PyMC)."""
    m4_path = _RESULTS / "m4-calibration-2026-06-03-2026-06-13.md"
    source_files: list[str] = []
    bins: list[CalibrationBinRow] = []
    notes: list[str] = []
    calibration_error: float | None = None
    brier: float | None = None
    n_contracts: int | None = None
    disagreement_note: str | None = None

    if m4_path.exists():
        text = m4_path.read_text()
        source_files.append(str(m4_path.relative_to(_REPO_ROOT)))
        bins = _parse_m4_bins(text)
        calibration_error = _first_float(r"Calibration error:\s*([0-9.]+)", text)
        brier = _first_float(r"Brier score:\s*([0-9.]+)", text)
        n_contracts = _first_int(r"Brier score:.*?on\s+(\d+)\s+contracts", text)
        if "Disagreement: not scored" in text:
            disagreement_note = "Disagreement not scored: no usable pre-tip mids in that window."
        elif "Disagreement:" in text:
            for line in text.splitlines():
                if line.startswith("Disagreement:"):
                    disagreement_note = line.strip()
                    break
        notes.append("Primary reliability bins from the M4 baseline replay.")
    else:
        notes.append("M4 calibration report missing under docs/results/.")

    props: list[PropCalibration] = []
    for prop, filename, version in (
        ("points", "m6-posterior.md", "pymc-m6-v1"),
        ("rebounds", "m6-posterior-rebounds.md", "pymc-m6-v1"),
        ("assists", "m6-posterior-assists.md", "pymc-m6-v1"),
    ):
        path = _RESULTS / filename
        if not path.exists():
            continue
        text = path.read_text()
        source_files.append(str(path.relative_to(_REPO_ROOT)))
        props.append(
            PropCalibration(
                prop_type=prop,
                model_version=version,
                brier=_first_float(r"Posterior Brier:\s*([0-9.]+)", text),
                residual_brier=_first_float(r"Residual-band Brier:\s*([0-9.]+)", text),
                n_contracts=_first_int(r"Posterior Brier:.*?on\s+(\d+)\s+contracts", text),
                source=str(path.relative_to(_REPO_ROOT)),
            )
        )

    m5 = _RESULTS / "m5-xgb.md"
    if m5.exists():
        text = m5.read_text()
        source_files.append(str(m5.relative_to(_REPO_ROOT)))
        props.append(
            PropCalibration(
                prop_type="all",
                model_version="xgb-m5-v1",
                brier=_first_float(r"XGBoost Brier:\s*([0-9.]+)", text),
                residual_brier=_first_float(r"Baseline Brier:\s*([0-9.]+)", text),
                n_contracts=_first_int(r"XGBoost Brier:.*?on\s+(\d+)\s+contracts", text),
                source=str(m5.relative_to(_REPO_ROOT)),
            )
        )

    return CalibrationSummaryResponse(
        title="Calibration summary (precomputed reports)",
        source_files=source_files,
        bins=bins,
        calibration_error=calibration_error,
        brier=brier,
        n_contracts=n_contracts,
        disagreement_note=disagreement_note,
        props=props,
        raw_notes=notes,
    )


def _table_freshness(
    session: Session,
    *,
    table: str,
    available_col: Any | None,
    ingested_col: Any | None,
    count_model: type,
) -> TableFreshness:
    max_available = None
    max_ingested = None
    if available_col is not None:
        max_available = session.exec(select(func.max(available_col))).one()
    if ingested_col is not None:
        max_ingested = session.exec(select(func.max(ingested_col))).one()
    count = session.exec(select(func.count()).select_from(count_model)).one()
    return TableFreshness(
        table=table,
        max_available_at=max_available,
        max_ingested_at=max_ingested,
        row_count=int(count) if count is not None else None,
    )


@router.get("/status", response_model=StatusResponse)
def system_status(session: Session = Depends(get_session)) -> StatusResponse:
    enabled = os.environ.get("SCHEDULER_ENABLED", "false").lower() == "true"
    scheduler = make_scheduler()
    job_ids = sorted(j.id for j in scheduler.get_jobs())
    freshness = [
        _table_freshness(
            session,
            table="player_game_logs",
            available_col=PlayerGameLog.available_at,
            ingested_col=PlayerGameLog.ingested_at,
            count_model=PlayerGameLog,
        ),
        _table_freshness(
            session,
            table="predictions",
            available_col=None,
            ingested_col=Prediction.ingested_at,
            count_model=Prediction,
        ),
        _table_freshness(
            session,
            table="market_snapshots",
            available_col=None,
            ingested_col=MarketSnapshot.ingested_at,
            count_model=MarketSnapshot,
        ),
        _table_freshness(
            session,
            table="injury_signals",
            available_col=InjurySignal.available_at,
            ingested_col=InjurySignal.ingested_at,
            count_model=InjurySignal,
        ),
    ]
    return StatusResponse(
        scheduler_enabled=enabled,
        job_ids=job_ids,
        freshness=freshness,
        api_version="m8-dashboard",
    )

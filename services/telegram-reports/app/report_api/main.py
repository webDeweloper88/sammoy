from __future__ import annotations

import socket
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status

from app.common.config import settings
from app.common.schemas import PeriodType, PostReport, PostTariffs, Tariff
from app.common.security import tokens_match
from app.report_api.repository import DemoReportRepository, PostgresReportRepository, ReportRepository

app = FastAPI(title="RTU WASH Report API", version="0.1.0", docs_url=None, redoc_url=None)


def repository() -> ReportRepository:
    if settings.repository_mode == "postgres":
        if not settings.postgres_dsn:
            raise RuntimeError("POSTGRES_DSN is required for postgres repository mode")
        return PostgresReportRepository(
            settings.postgres_dsn, settings.site_id, settings.post_id, settings.post_name
        )
    return DemoReportRepository(settings.site_id, settings.post_id, settings.post_name)


def authorize(authorization: str = Header(default="")) -> None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not tokens_match(token, settings.local_report_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")


def bounds(period_type: PeriodType, value: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.timezone)
    if period_type == "daily":
        start_date, end_date = value, value + timedelta(days=1)
    elif period_type == "weekly":
        start_date = value - timedelta(days=value.weekday())
        end_date = start_date + timedelta(days=7)
    else:
        start_date = value.replace(day=1)
        end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    return datetime.combine(start_date, time.min, tz), datetime.combine(end_date, time.min, tz)


@app.get("/api/v1/health")
def health(_: None = Depends(authorize)) -> dict[str, object]:
    return {
        "status": "ok",
        "site_id": settings.site_id,
        "post_id": settings.post_id,
        "node_id": socket.gethostname(),
        "service": "rtu-wash-report-api",
        "version": app.version,
        "repository": settings.repository_mode,
        "timestamp": datetime.now(ZoneInfo(settings.timezone)),
    }


@app.get("/api/v1/reports/{period_type}", response_model=PostReport)
def report(
    period_type: PeriodType,
    value: date | None = None,
    _: None = Depends(authorize),
) -> PostReport:
    report_date = value or datetime.now(ZoneInfo(settings.timezone)).date()
    start_at, end_at = bounds(period_type, report_date)
    return repository().get_report(period_type, start_at, end_at)


@app.get("/api/v1/tariffs", response_model=PostTariffs)
async def tariffs(_: None = Depends(authorize)) -> PostTariffs:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{settings.wash_engine_url.rstrip('/')}/api/wash/state")
            response.raise_for_status()
        raw_tariffs = response.json().get("parameters", {}).get("tariffs", {})
        if not isinstance(raw_tariffs, dict):
            raise TypeError("tariffs payload is not an object")
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Wash tariffs are unavailable") from exc

    mode_order = ["water", "foam", "chem", "nano", "wax", "vacuum", "air", "osmos", "pause"]
    ordered_modes = [mode for mode in mode_order if mode in raw_tariffs]
    ordered_modes.extend(sorted(set(raw_tariffs) - set(ordered_modes)))
    result: list[Tariff] = []
    for mode in ordered_modes:
        value = raw_tariffs.get(mode)
        if not isinstance(value, dict):
            continue
        result.append(
            Tariff(
                mode=mode,
                amount_sum=max(0, int(value.get("amountSum") or 0)),
                duration_seconds=max(0, int(value.get("durationSeconds") or 0)),
                sum_per_minute=max(0, int(value.get("sumPerMinute") or 0)),
                enabled=value.get("enabled") is not False,
            )
        )
    return PostTariffs(
        site_id=settings.site_id,
        post_id=settings.post_id,
        post_name=settings.post_name,
        tariffs=result,
        generated_at=datetime.now(ZoneInfo(settings.timezone)),
    )

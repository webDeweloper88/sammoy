from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException

from app.common.config import load_hub_config, settings
from app.common.schemas import AggregateReport, AggregateTariffs, PeriodType
from app.hub.aggregator import ReportAggregator

app = FastAPI(title="RTU WASH Local Report Hub", version="0.1.0", docs_url=None, redoc_url=None)
_aggregator: ReportAggregator | None = None


def aggregator() -> ReportAggregator:
    global _aggregator
    if not settings.posts_config.exists():
        raise HTTPException(503, "Posts configuration is missing")
    if _aggregator is None:
        _aggregator = ReportAggregator(
            load_hub_config(settings.posts_config),
            timeout=settings.report_request_timeout_seconds,
            cache_seconds=settings.report_cache_seconds,
        )
    return _aggregator


@app.get("/api/v1/health")
def health() -> dict[str, object]:
    config = load_hub_config(settings.posts_config)
    return {
        "status": "ok",
        "service": "rtu-wash-local-hub",
        "configured_posts": len([post for post in config.posts if post.enabled]),
        "timestamp": datetime.now(ZoneInfo(config.site.timezone)),
    }


@app.get("/api/v1/aggregate/{period_type}", response_model=AggregateReport)
async def aggregate(
    period_type: PeriodType, value: date | None = None, refresh: bool = False
) -> AggregateReport:
    global _aggregator
    if refresh:
        _aggregator = None
    config = load_hub_config(settings.posts_config)
    selected = value or datetime.now(ZoneInfo(config.site.timezone)).date()
    return await aggregator().aggregate(period_type, selected)


@app.get("/api/v1/tariffs", response_model=AggregateTariffs)
async def tariffs(refresh: bool = False) -> AggregateTariffs:
    global _aggregator
    if refresh:
        _aggregator = None
    return await aggregator().tariffs()

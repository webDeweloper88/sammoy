from __future__ import annotations

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from app.common.config import HubConfig, PostConfig
from app.common.schemas import (
    AggregateReport,
    AggregateSummary,
    AggregateTariffs,
    PeriodType,
    PostReport,
    PostResult,
    PostTariffs,
    TariffResult,
)


class ReportAggregator:
    def __init__(self, config: HubConfig, timeout: float = 3.0, cache_seconds: int = 45):
        self.config = config
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, AggregateReport]] = {}

    async def _fetch(self, client: httpx.AsyncClient, post: PostConfig, period: PeriodType, value: date) -> PostResult:
        url = f"http://{post.host}:{post.port}/api/v1/reports/{period}"
        last_error = "unavailable"
        for attempt in range(2):
            try:
                response = await client.get(
                    url,
                    params={"value": value.isoformat()},
                    headers={"Authorization": f"Bearer {post.api_key}"},
                )
                response.raise_for_status()
                report = PostReport.model_validate(response.json())
                if report.site_id != self.config.site.id or report.post_id != post.id:
                    raise ValueError("Report identity mismatch")
                return PostResult(post_id=post.id, name=post.name, status="online", report=report)
            except httpx.HTTPStatusError as exc:
                last_error = "authentication" if exc.response.status_code == 401 else f"http_{exc.response.status_code}"
                if exc.response.status_code == 401:
                    break
            except (httpx.TimeoutException, httpx.NetworkError):
                last_error = "timeout"
            except (ValueError, TypeError):
                last_error = "invalid_response"
            if attempt == 0:
                await asyncio.sleep(0.1)
        return PostResult(post_id=post.id, name=post.name, status="offline", error=last_error)

    async def aggregate(self, period: PeriodType, value: date) -> AggregateReport:
        key = f"{period}:{value.isoformat()}"
        now = asyncio.get_running_loop().time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self.cache_seconds:
            return cached[1]

        posts = [post for post in self.config.posts if post.enabled]
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            results = await asyncio.gather(*(self._fetch(client, post, period, value) for post in posts))
        online = [item.report for item in results if item.report is not None]
        generated_at = datetime.now(ZoneInfo(self.config.site.timezone))
        if not online:
            result = AggregateReport(
                site_id=self.config.site.id,
                site_name=self.config.site.name,
                status="data_unavailable",
                period_type=period,
                period_from=None,
                period_to=None,
                summary=None,
                posts=results,
                generated_at=generated_at,
            )
        else:
            cash = sum(item.cash_amount for item in online)
            click = sum(item.click_amount for item in online)
            sessions = sum(item.total_sessions for item in online)
            total = cash + click
            result = AggregateReport(
                site_id=self.config.site.id,
                site_name=self.config.site.name,
                status="ok" if len(online) == len(results) else "partial",
                period_type=period,
                period_from=min(item.period_from for item in online),
                period_to=max(item.period_to for item in online),
                summary=AggregateSummary(
                    cash_amount=cash,
                    click_amount=click,
                    total_amount=total,
                    total_sessions=sessions,
                    average_check=total // sessions if sessions else 0,
                    working_seconds=sum(item.working_seconds for item in online),
                    online_posts=len(online),
                    offline_posts=len(results) - len(online),
                ),
                posts=results,
                generated_at=generated_at,
            )
        self._cache[key] = (now, result)
        return result

    async def _fetch_tariffs(self, client: httpx.AsyncClient, post: PostConfig) -> TariffResult:
        url = f"http://{post.host}:{post.port}/api/v1/tariffs"
        last_error = "unavailable"
        for attempt in range(2):
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {post.api_key}"},
                )
                response.raise_for_status()
                tariffs = PostTariffs.model_validate(response.json())
                return TariffResult(post_id=post.id, name=post.name, status="online", tariffs=tariffs)
            except httpx.HTTPStatusError as exc:
                last_error = "authentication" if exc.response.status_code == 401 else f"http_{exc.response.status_code}"
                if exc.response.status_code == 401:
                    break
            except (httpx.TimeoutException, httpx.NetworkError):
                last_error = "timeout"
            except (ValueError, TypeError):
                last_error = "invalid_response"
            if attempt == 0:
                await asyncio.sleep(0.1)
        return TariffResult(post_id=post.id, name=post.name, status="offline", error=last_error)

    async def tariffs(self) -> AggregateTariffs:
        posts = [post for post in self.config.posts if post.enabled]
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            results = await asyncio.gather(*(self._fetch_tariffs(client, post) for post in posts))
        online = [item for item in results if item.tariffs is not None]
        return AggregateTariffs(
            site_id=self.config.site.id,
            site_name=self.config.site.name,
            status=(
                "data_unavailable"
                if not online
                else "ok"
                if len(online) == len(results)
                else "partial"
            ),
            posts=results,
            generated_at=datetime.now(ZoneInfo(self.config.site.timezone)),
        )

import asyncio
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import setup_agent
from app.common.config import HubConfig, PostConfig, SiteConfig, settings
from app.common.schemas import (
    AggregateReport,
    AggregateSummary,
    AggregateTariffs,
    PostReport,
    PostResult,
    PostTariffs,
    Tariff,
    TariffResult,
)
from app.hub.aggregator import ReportAggregator
from app.report_api.main import app as report_api_app
from app.report_api.main import bounds
from app.telegram_bot.dedup import DuplicateMessageGuard
from app.telegram_bot.formatter import (
    format_payments,
    format_posts,
    format_report,
    format_status,
    format_tariffs,
)
from app.telegram_bot.health import HealthTracker
from app.telegram_bot.store import PairingStore

TZ = ZoneInfo("Asia/Tashkent")


def sample_post(post_id: str = "POST-01") -> PostReport:
    return PostReport(
        site_id="SITE-1",
        post_id=post_id,
        post_name="Post 1",
        period_type="daily",
        period_from=datetime(2026, 7, 31, tzinfo=TZ),
        period_to=datetime(2026, 8, 1, tzinfo=TZ),
        cash_amount=1_000,
        click_amount=2_000,
        total_sessions=3,
        working_seconds=100,
        error_count=0,
        generated_at=datetime(2026, 7, 31, 12, tzinfo=TZ),
    )


def test_report_computed_values() -> None:
    report = sample_post()
    assert report.total_amount == 3_000
    assert report.average_check == 1_000


def test_week_starts_on_monday() -> None:
    start, end = bounds("weekly", date(2026, 7, 31))
    assert start.date().isoformat() == "2026-07-27"
    assert end.date().isoformat() == "2026-08-03"


def test_pairing_is_single_use_and_owner_persists(tmp_path: Path) -> None:
    store = PairingStore(tmp_path / "hub.sqlite3")
    token, _ = store.create_token(10)
    assert store.claim(token, 123, "owner", "Owner") is True
    assert store.claim(token, 456, "other", "Other") is False
    assert PairingStore(tmp_path / "hub.sqlite3").is_owner(123) is True
    assert store.is_owner(456) is False


def test_owner_reset(tmp_path: Path) -> None:
    store = PairingStore(tmp_path / "hub.sqlite3")
    token, _ = store.create_token(10)
    assert store.claim(token, 123, None, None)
    assert store.reset_owner()
    assert not store.is_owner(123)


def test_notification_state_persists(tmp_path: Path) -> None:
    path = tmp_path / "hub.sqlite3"
    store = PairingStore(path)
    assert store.state("automatic_daily_report_date") is None
    store.set_state("automatic_daily_report_date", "2026-08-01")
    assert PairingStore(path).state("automatic_daily_report_date") == "2026-08-01"


@pytest.mark.asyncio
async def test_duplicate_message_guard_rejects_concurrent_duplicate() -> None:
    guard = DuplicateMessageGuard(ttl_seconds=2)
    key = (100, 200, "Postlar holati")

    results = await asyncio.gather(
        guard.accept(key, now=10),
        guard.accept(key, now=10),
    )

    assert results.count(True) == 1
    assert results.count(False) == 1
    assert await guard.accept(key, now=12) is True


def test_setup_env_update_preserves_values_and_never_exposes_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "reports.env"
    data_path = tmp_path / "hub.sqlite3"
    env_path.write_text("KEEP=value\nTELEGRAM_BOT_TOKEN=old-secret\n", encoding="utf-8")
    monkeypatch.setattr(setup_agent, "ENV_PATH", env_path)
    monkeypatch.setattr(setup_agent, "DATA_PATH", data_path)
    monkeypatch.setattr(setup_agent.grp, "getgrnam", lambda _: type("Group", (), {"gr_gid": 0})())
    monkeypatch.setattr(setup_agent.os, "chown", lambda *args: None)
    monkeypatch.setattr(setup_agent, "service_active", lambda _: False)

    setup_agent.write_env(
        {
            "TELEGRAM_BOT_TOKEN": "new-secret",
            "TELEGRAM_BOT_USERNAME": "test_bot",
            "SITE_NAME": "RTU WASH Demo",
        }
    )

    assert setup_agent.read_env()["KEEP"] == "value"
    assert setup_agent.read_env()["TELEGRAM_BOT_TOKEN"] == "new-secret"
    assert setup_agent.read_env()["SITE_NAME"] == "RTU WASH Demo"
    assert "SITE_NAME='RTU WASH Demo'" in env_path.read_text(encoding="utf-8")
    payload = setup_agent.public_status()
    assert payload["token_saved"] is True
    assert "new-secret" not in str(payload)


def test_site_report_key_is_stable_and_context_bound() -> None:
    first = setup_agent.report_key("site-token")
    assert first == setup_agent.report_key("site-token")
    assert first != setup_agent.report_key("other-site-token")
    assert len(first) == 64


def test_mobile_token_setup_is_post_one_only_and_single_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_agent.mobile_sessions.clear()
    monkeypatch.setattr(setup_agent, "orange_identity", lambda: ("SITE-1", 1, "site-token"))

    async def fake_configure(payload: setup_agent.ConfigureRequest) -> dict[str, object]:
        assert payload.post_no == 1
        assert payload.site_id == "SITE-1"
        assert payload.token == "123456789:valid-token-value_abcdefghijklmnopqrstuvwxyz"
        return {"bot_username": "reports_bot"}

    monkeypatch.setattr(setup_agent, "configure", fake_configure)
    client = TestClient(setup_agent.app)
    created = client.post("/mobile/session", headers={"host": "10.10.10.6"})
    assert created.status_code == 200
    body = created.json()
    assert body["mobile_url"].startswith("http://10.10.10.6/api/telegram-setup/mobile/")
    assert body["qr_data_url"].startswith("data:image/png;base64,")
    raw = urlparse(body["mobile_url"]).path.rsplit("/", 1)[1]
    assert client.get(f"/mobile/{raw}").status_code == 200

    configured = client.post(
        f"/mobile/{raw}/configure",
        json={"token": "123456789:valid-token-value_abcdefghijklmnopqrstuvwxyz"},
    )
    assert configured.status_code == 200
    assert configured.json()["bot_username"] == "reports_bot"
    assert client.get(f"/mobile/{raw}").status_code == 410


def test_mobile_token_setup_rejects_secondary_post(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_agent.mobile_sessions.clear()
    monkeypatch.setattr(setup_agent, "orange_identity", lambda: ("SITE-1", 2, "site-token"))
    response = TestClient(setup_agent.app).post("/mobile/session")
    assert response.status_code == 409
    assert "Post 1" in response.json()["detail"]


def test_health_tracker_alerts_once_and_recovers(tmp_path: Path) -> None:
    tracker = HealthTracker(PairingStore(tmp_path / "hub.sqlite3"), failure_threshold=3)
    assert tracker.observe("post:POST-01", True) is None
    assert tracker.observe("post:POST-01", False) is None
    assert tracker.observe("post:POST-01", False) is None
    offline = tracker.observe("post:POST-01", False)
    assert offline is not None
    assert offline.kind == "offline"
    assert offline.failures == 3
    tracker.acknowledge(offline)
    assert tracker.observe("post:POST-01", False) is None
    recovered = tracker.observe("post:POST-01", True)
    assert recovered is not None
    assert recovered.kind == "recovered"
    tracker.acknowledge(recovered)
    assert tracker.observe("post:POST-01", True) is None


def test_partial_report_warns_owner() -> None:
    post = sample_post()
    aggregate = AggregateReport(
        site_id="SITE-1",
        site_name="RTU WASH Test",
        status="partial",
        period_type="daily",
        period_from=post.period_from,
        period_to=post.period_to,
        summary=AggregateSummary(
            cash_amount=1_000,
            click_amount=2_000,
            total_amount=3_000,
            total_sessions=3,
            average_check=1_000,
            working_seconds=100,
            online_posts=1,
            offline_posts=1,
        ),
        posts=[
            PostResult(post_id="POST-01", name="Post 1", status="online", report=post),
            PostResult(post_id="POST-02", name="Post 2", status="offline", error="timeout"),
        ],
        generated_at=datetime(2026, 7, 31, 12, tzinfo=TZ),
    )
    text = format_report(aggregate)
    assert "3 000 so‘m" in text
    assert "Post 2: OFFLINE" in text
    assert "to‘liq jami emas" in text
    assert "Post 2: timeout" in format_status(aggregate)
    assert "Naqd: 1 000 so‘m" in format_payments(aggregate)
    assert "Post 1" in format_posts(aggregate)


@pytest.mark.asyncio
async def test_aggregator_keeps_partial_results(monkeypatch: pytest.MonkeyPatch) -> None:
    config = HubConfig(
        site=SiteConfig(id="SITE-1", name="Test"),
        posts=[
            PostConfig(id="POST-01", name="Post 1", host="one", api_key_env="KEY_1"),
            PostConfig(id="POST-02", name="Post 2", host="two", api_key_env="KEY_2"),
        ],
    )
    aggregator = ReportAggregator(config)

    async def fake_fetch(client, post, period, value):
        if post.id == "POST-01":
            return PostResult(post_id=post.id, name=post.name, status="online", report=sample_post())
        return PostResult(post_id=post.id, name=post.name, status="offline", error="timeout")

    monkeypatch.setattr(aggregator, "_fetch", fake_fetch)
    result = await aggregator.aggregate("daily", date(2026, 7, 31))
    assert result.status == "partial"
    assert result.summary is not None
    assert result.summary.total_amount == 3_000
    assert result.summary.offline_posts == 1


@pytest.mark.asyncio
async def test_all_offline_is_not_reported_as_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    config = HubConfig(
        site=SiteConfig(id="SITE-1", name="Test"),
        posts=[PostConfig(id="POST-01", name="Post 1", host="one", api_key_env="KEY_1")],
    )
    aggregator = ReportAggregator(config)

    async def offline(client, post, period, value):
        return PostResult(post_id=post.id, name=post.name, status="offline", error="timeout")

    monkeypatch.setattr(aggregator, "_fetch", offline)
    result = await aggregator.aggregate("daily", date(2026, 7, 31))
    assert result.status == "data_unavailable"
    assert result.summary is None


def test_report_api_rejects_invalid_token() -> None:
    response = TestClient(report_api_app).get(
        "/api/v1/health", headers={"Authorization": "Bearer definitely-wrong"}
    )
    assert response.status_code == 401


def test_report_api_returns_integer_money() -> None:
    response = TestClient(report_api_app).get(
        "/api/v1/reports/daily",
        params={"value": "2026-07-31"},
        headers={"Authorization": f"Bearer {settings.local_report_api_key}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["cash_amount"], int)
    assert isinstance(payload["total_amount"], int)


def test_report_api_returns_read_only_tariffs(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "parameters": {
                    "tariffs": {
                        "water": {
                            "amountSum": 1_000,
                            "durationSeconds": 40,
                            "sumPerMinute": 1_500,
                            "enabled": True,
                        }
                    }
                }
            }

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            assert url.endswith("/api/wash/state")
            return FakeResponse()

    monkeypatch.setattr("app.report_api.main.httpx.AsyncClient", FakeAsyncClient)
    response = TestClient(report_api_app).get(
        "/api/v1/tariffs",
        headers={"Authorization": f"Bearer {settings.local_report_api_key}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tariffs"][0]["mode"] == "water"
    assert payload["tariffs"][0]["amount_sum"] == 1_000


def sample_tariffs(post_id: str = "POST-01") -> PostTariffs:
    return PostTariffs(
        site_id="SITE-1",
        post_id=post_id,
        post_name="Post 1",
        tariffs=[
            Tariff(
                mode="water",
                amount_sum=1_000,
                duration_seconds=40,
                sum_per_minute=1_500,
                enabled=True,
            ),
            Tariff(
                mode="air",
                amount_sum=1_000,
                duration_seconds=20,
                sum_per_minute=3_000,
                enabled=False,
            ),
        ],
        generated_at=datetime(2026, 8, 1, 12, tzinfo=TZ),
    )


def test_tariff_formatter_is_read_only_and_includes_current_values() -> None:
    payload = AggregateTariffs(
        site_id="SITE-1",
        site_name="RTU WASH Test",
        status="ok",
        posts=[
            TariffResult(
                post_id="POST-01",
                name="Post 1",
                status="online",
                tariffs=sample_tariffs(),
            )
        ],
        generated_at=datetime(2026, 8, 1, 12, tzinfo=TZ),
    )
    text = format_tariffs(payload)
    assert "1 000 so‘m / 40 soniya" in text
    assert "1 500 so‘m/min" in text
    assert "Havo: o‘chirilgan" in text
    assert "o‘zgartirish o‘chirilgan" in text


@pytest.mark.asyncio
async def test_tariff_aggregator_keeps_partial_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = HubConfig(
        site=SiteConfig(id="SITE-1", name="Test"),
        posts=[
            PostConfig(id="POST-01", name="Post 1", host="one", api_key_env="KEY_1"),
            PostConfig(id="POST-02", name="Post 2", host="two", api_key_env="KEY_2"),
        ],
    )
    aggregator = ReportAggregator(config)

    async def fake_fetch_tariffs(client, post):
        if post.id == "POST-01":
            return TariffResult(
                post_id=post.id,
                name=post.name,
                status="online",
                tariffs=sample_tariffs(),
            )
        return TariffResult(post_id=post.id, name=post.name, status="offline", error="timeout")

    monkeypatch.setattr(aggregator, "_fetch_tariffs", fake_fetch_tariffs)
    result = await aggregator.tariffs()
    assert result.status == "partial"
    assert result.posts[0].tariffs is not None
    assert result.posts[1].error == "timeout"

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from app.common.schemas import ModeTotal, PeriodType, PostReport


class ReportRepository(Protocol):
    def get_report(self, period_type: PeriodType, start_at: datetime, end_at: datetime) -> PostReport: ...


class PostgresReportRepository:
    """Read-only adapter for the RTU WASH Postgres ledger."""

    def __init__(self, dsn: str, site_id: str, post_id: str, post_name: str):
        self.dsn = dsn
        self.site_id = site_id
        self.post_id = post_id
        self.post_name = post_name

    def get_report(self, period_type: PeriodType, start_at: datetime, end_at: datetime) -> PostReport:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            payments = conn.execute(
                """
                SELECT provider, COALESCE(sum(amount_sum), 0)::bigint AS amount
                FROM payments
                WHERE created_at >= %s AND created_at < %s
                  AND status IN ('paid', 'credited') AND provider IN ('cash', 'click')
                GROUP BY provider
                """,
                (start_at, end_at),
            ).fetchall()
            sessions = conn.execute(
                "SELECT count(*)::bigint AS count FROM wash_sessions WHERE started_at >= %s AND started_at < %s",
                (start_at, end_at),
            ).fetchone()
            modes = conn.execute(
                """
                SELECT mode, (COALESCE(sum(duration_ms), 0) / 1000)::bigint AS working_seconds,
                       COALESCE(sum(spent_sum), 0)::bigint AS spent_sum
                FROM mode_usage WHERE started_at >= %s AND started_at < %s
                GROUP BY mode ORDER BY spent_sum DESC
                """,
                (start_at, end_at),
            ).fetchall()
            errors = conn.execute(
                """
                SELECT count(*)::bigint AS count FROM system_events
                WHERE created_at >= %s AND created_at < %s AND level IN ('error', 'critical')
                """,
                (start_at, end_at),
            ).fetchone()

        by_provider = {row["provider"]: int(row["amount"]) for row in payments}
        mode_totals = [ModeTotal.model_validate(row) for row in modes]
        return PostReport(
            site_id=self.site_id,
            post_id=self.post_id,
            post_name=self.post_name,
            period_type=period_type,
            period_from=start_at,
            period_to=end_at,
            cash_amount=by_provider.get("cash", 0),
            click_amount=by_provider.get("click", 0),
            total_sessions=int(sessions["count"]),
            working_seconds=sum(mode.working_seconds for mode in mode_totals),
            error_count=int(errors["count"]),
            modes=mode_totals,
            generated_at=datetime.now(start_at.tzinfo),
        )


class DemoReportRepository:
    def __init__(self, site_id: str, post_id: str, post_name: str):
        self.site_id = site_id
        self.post_id = post_id
        self.post_name = post_name

    def get_report(self, period_type: PeriodType, start_at: datetime, end_at: datetime) -> PostReport:
        seed = sum(ord(char) for char in self.post_id)
        days = max(1, (end_at - start_at).days)
        cash = (220_000 + seed * 1_000) * days
        click = (310_000 + seed * 1_250) * days
        sessions = (18 + seed % 12) * days
        return PostReport(
            site_id=self.site_id,
            post_id=self.post_id,
            post_name=self.post_name,
            period_type=period_type,
            period_from=start_at,
            period_to=end_at,
            cash_amount=cash,
            click_amount=click,
            total_sessions=sessions,
            working_seconds=18_000 * days,
            error_count=0,
            modes=[
                ModeTotal(mode="water", working_seconds=9_000 * days, spent_sum=(cash + click) // 2),
                ModeTotal(mode="foam", working_seconds=5_400 * days, spent_sum=(cash + click) // 3),
            ],
            generated_at=datetime.now(start_at.tzinfo),
        )

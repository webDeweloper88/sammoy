from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

PeriodType = Literal["daily", "weekly", "monthly"]


class ModeTotal(BaseModel):
    mode: str
    working_seconds: int = 0
    spent_sum: int = 0


class PostReport(BaseModel):
    site_id: str
    post_id: str
    post_name: str
    period_type: PeriodType
    period_from: datetime
    period_to: datetime
    cash_amount: int = Field(ge=0)
    click_amount: int = Field(ge=0)
    total_sessions: int = Field(ge=0)
    working_seconds: int = Field(ge=0)
    error_count: int = Field(ge=0)
    modes: list[ModeTotal] = Field(default_factory=list)
    generated_at: datetime

    @computed_field
    @property
    def total_amount(self) -> int:
        return self.cash_amount + self.click_amount

    @computed_field
    @property
    def average_check(self) -> int:
        return self.total_amount // self.total_sessions if self.total_sessions else 0


class PostResult(BaseModel):
    post_id: str
    name: str
    status: Literal["online", "offline"]
    report: PostReport | None = None
    error: str | None = None


class AggregateSummary(BaseModel):
    cash_amount: int
    click_amount: int
    total_amount: int
    total_sessions: int
    average_check: int
    working_seconds: int
    online_posts: int
    offline_posts: int


class AggregateReport(BaseModel):
    site_id: str
    site_name: str
    status: Literal["ok", "partial", "data_unavailable"]
    period_type: PeriodType
    period_from: datetime | None
    period_to: datetime | None
    summary: AggregateSummary | None
    posts: list[PostResult]
    generated_at: datetime


class Tariff(BaseModel):
    mode: str
    amount_sum: int = Field(ge=0)
    duration_seconds: int = Field(ge=0)
    sum_per_minute: int = Field(ge=0)
    enabled: bool = True


class PostTariffs(BaseModel):
    site_id: str
    post_id: str
    post_name: str
    tariffs: list[Tariff] = Field(default_factory=list)
    generated_at: datetime


class TariffResult(BaseModel):
    post_id: str
    name: str
    status: Literal["online", "offline"]
    tariffs: PostTariffs | None = None
    error: str | None = None


class AggregateTariffs(BaseModel):
    site_id: str
    site_name: str
    status: Literal["ok", "partial", "data_unavailable"]
    posts: list[TariffResult]
    generated_at: datetime

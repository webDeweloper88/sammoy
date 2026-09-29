from __future__ import annotations

from app.common.schemas import AggregateReport, AggregateTariffs

MODE_LABELS = {
    "water": "Suv",
    "foam": "Ko‘pik",
    "chem": "Kimyo",
    "nano": "Nano",
    "wax": "Mum",
    "vacuum": "Changyutgich",
    "air": "Havo",
    "osmos": "Osmos",
    "pause": "Pauza",
}


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def format_report(report: AggregateReport) -> str:
    title = {"daily": "Bugungi hisobot", "weekly": "Haftalik hisobot", "monthly": "Oylik hisobot"}[
        report.period_type
    ]
    if report.status == "data_unavailable" or report.summary is None:
        offline = ", ".join(item.name for item in report.posts) or "barcha postlar"
        return f"🏪 {report.site_name}\n⚠️ Hisobot mavjud emas\nJavob bermadi: {offline}"

    summary = report.summary
    lines = [
        f"🏪 {report.site_name}",
        f"📊 {title}",
        "",
        f"💰 Jami: {money(summary.total_amount)} so‘m",
        f"💵 Naqd: {money(summary.cash_amount)} so‘m",
        f"💳 Click: {money(summary.click_amount)} so‘m",
        "",
        f"🧾 Tranzaksiyalar: {summary.total_sessions} ta",
        f"📌 O‘rtacha chek: {money(summary.average_check)} so‘m",
        "",
    ]
    for item in report.posts:
        if item.report:
            lines.append(f"{item.name}: {money(item.report.total_amount)} so‘m")
        else:
            lines.append(f"{item.name}: OFFLINE")
    if summary.offline_posts:
        lines.extend(
            [
                "",
                "⚠️ Bu to‘liq jami emas. Offline postlar ma’lumoti hisobga kiritilmadi.",
            ]
        )
    lines.append(f"🕒 {report.generated_at:%d.%m.%Y %H:%M}")
    return "\n".join(lines)


def format_status(report: AggregateReport) -> str:
    lines = [f"🏪 {report.site_name}", "⚠️ Postlar holati", ""]
    for item in report.posts:
        marker = "🟢" if item.status == "online" else "🔴"
        detail = "online" if item.status == "online" else item.error or "offline"
        lines.append(f"{marker} {item.name}: {detail}")
    lines.extend(["", f"🕒 {report.generated_at:%d.%m.%Y %H:%M}"])
    return "\n".join(lines)


def format_payments(report: AggregateReport) -> str:
    if report.summary is None:
        return format_report(report)
    summary = report.summary
    return "\n".join(
        [
            f"🏪 {report.site_name}",
            "💳 Naqd / Click",
            "",
            f"💵 Naqd: {money(summary.cash_amount)} so‘m",
            f"💳 Click: {money(summary.click_amount)} so‘m",
            f"💰 Jami: {money(summary.total_amount)} so‘m",
            "",
            f"🕒 {report.generated_at:%d.%m.%Y %H:%M}",
        ]
    )


def format_posts(report: AggregateReport) -> str:
    lines = [f"🏪 {report.site_name}", "🏪 Postlar bo‘yicha", ""]
    for item in report.posts:
        if item.report:
            lines.extend(
                [
                    f"🟢 {item.name}",
                    f"   Jami: {money(item.report.total_amount)} so‘m",
                    f"   Naqd: {money(item.report.cash_amount)} | Click: {money(item.report.click_amount)}",
                ]
            )
        else:
            lines.append(f"🔴 {item.name}: OFFLINE ({item.error or 'unavailable'})")
    return "\n".join(lines)


def format_tariffs(report: AggregateTariffs) -> str:
    lines = [f"🏪 {report.site_name}", "💰 Joriy tariflar", "🔒 Faqat ko‘rish", ""]
    for post in report.posts:
        if post.tariffs is None:
            lines.append(f"🔴 {post.name}: OFFLINE ({post.error or 'unavailable'})")
            continue
        lines.append(f"🟢 {post.name}")
        for tariff in post.tariffs.tariffs:
            label = MODE_LABELS.get(tariff.mode, tariff.mode)
            if not tariff.enabled:
                lines.append(f"   ⚪ {label}: o‘chirilgan")
            elif tariff.amount_sum <= 0 or tariff.duration_seconds <= 0:
                lines.append(f"   • {label}: bepul")
            else:
                lines.append(
                    f"   • {label}: {money(tariff.amount_sum)} so‘m / "
                    f"{tariff.duration_seconds} soniya "
                    f"({money(tariff.sum_per_minute)} so‘m/min)"
                )
        lines.append("")
    if report.status == "partial":
        lines.append("⚠️ Ayrim postlar javob bermadi.")
    elif report.status == "data_unavailable":
        lines.append("⚠️ Tarif ma’lumotlari mavjud emas.")
    lines.append("Telegram orqali tariflarni o‘zgartirish o‘chirilgan.")
    lines.append(f"🕒 {report.generated_at:%d.%m.%Y %H:%M}")
    return "\n".join(lines)

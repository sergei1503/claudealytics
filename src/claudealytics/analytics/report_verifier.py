"""Report verification against data_json."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from claudealytics.models.schemas import FullReport


@dataclass
class VerificationCheck:
    metric: str
    report_value: float | None
    actual_value: float | None
    matches: bool
    note: str = ""


@dataclass
class ReportVerification:
    checks: list[VerificationCheck] = field(default_factory=list)
    total_checked: int = 0
    total_matched: int = 0
    total_mismatched: int = 0
    total_missing: int = 0

    @property
    def pass_rate(self) -> float:
        if self.total_checked == 0:
            return 100.0
        return round((self.total_matched / self.total_checked) * 100, 1)


def verify_report(report: FullReport) -> ReportVerification:
    if not report.report_markdown or not report.data_json:
        return ReportVerification()

    md = report.report_markdown
    data = report.data_json
    checks: list[VerificationCheck] = []

    activity = data.get("activity", {})
    if "total_sessions" in activity:
        checks.append(
            _check_number(md, "Total sessions", activity["total_sessions"], [r"(\d[\d,]*)\s*(?:total\s+)?sessions"])
        )
    if "total_messages" in activity:
        checks.append(
            _check_number(md, "Total messages", activity["total_messages"], [r"(\d[\d,]*)\s*(?:total\s+)?messages"])
        )
    if "total_cost_usd" in activity:
        checks.append(
            _check_number(
                md,
                "Total cost (USD)",
                activity["total_cost_usd"],
                [
                    r"\$\s*([\d,]+\.?\d*)\s*(?:total\s+)?(?:cost|spent|spend)",
                    r"total\s+cost[:\s]*\$\s*([\d,]+\.?\d*)",
                    r"\$([\d,]+\.?\d*)\s*(?:reported)?\s*cost",
                ],
                is_currency=True,
            )
        )
    if "top_model_by_cost" in activity:
        checks.append(_check_text(md, "Top model by cost", activity["top_model_by_cost"]))

    tokens = data.get("tokens", {})
    if "avg_daily_7d" in tokens:
        checks.append(
            _check_number(
                md,
                "Avg daily tokens (7d)",
                tokens["avg_daily_7d"],
                [r"(?:average|avg)\s+daily\s+tokens[^:]*?:?\s*([\d,]+)"],
            )
        )

    cache = data.get("cache", {})
    if "hit_rate" in cache:
        checks.append(
            _check_number(
                md,
                "Cache hit rate (%)",
                cache["hit_rate"],
                [r"cache\s+hit\s+rate[:\s]*([\d.]+)\s*%", r"([\d.]+)\s*%\s*cache\s+hit", r"([\d.]+)\s*%\s*hit\s+rate"],
            )
        )

    content = data.get("content", {})
    if "total_errors" in content:
        checks.append(
            _check_number(
                md,
                "Total errors",
                content["total_errors"],
                [r"(\d[\d,]*)\s*(?:total\s+)?error(?:s|\s+events)", r"errors?[:\s]*([\d,]+)"],
            )
        )
    if "sessions_analyzed" in content:
        checks.append(
            _check_number(
                md,
                "Sessions analyzed",
                content["sessions_analyzed"],
                [r"(\d[\d,]*)\s*sessions?\s+(?:analyzed|scanned)", r"(\d[\d,]*)\s*sessions"],
            )
        )

    as_data = data.get("agents_skills", {})
    if "unique_agents" in as_data:
        checks.append(_check_number(md, "Unique agents", as_data["unique_agents"], [r"(\d[\d,]*)\s+unique\s+agents?"]))
    if "unique_skills" in as_data:
        checks.append(_check_number(md, "Unique skills", as_data["unique_skills"], [r"(\d[\d,]*)\s+unique\s+skills?"]))
    if "total_conversations" in as_data:
        checks.append(
            _check_number(
                md,
                "Total conversations",
                as_data["total_conversations"],
                [r"(\d[\d,]*)\s*(?:total\s+)?conversations?", r"(\d[\d,]*)\s*conversations"],
            )
        )

    opt = data.get("optimization", {})
    if "unused_agents" in opt:
        checks.append(_check_number(md, "Unused agents", opt["unused_agents"], [r"(\d+)\s*unused\s+agents?"]))
    if "unused_skills" in opt:
        checks.append(_check_number(md, "Unused skills", opt["unused_skills"], [r"(\d+)\s*unused\s+skills?"]))

    ch = data.get("config_health", {})
    if "health_score" in ch:
        checks.append(
            _check_number(
                md,
                "Config health score",
                ch["health_score"],
                [
                    r"health\s+score[:\s]*([\d]+)\s*/\s*100",
                    r"([\d]+)\s*/\s*100\s*health",
                    r"score[:\s]*([\d]+)\s*/\s*100",
                ],
            )
        )

    result = ReportVerification(checks=checks)
    result.total_checked = len([c for c in checks if c.report_value is not None])
    result.total_matched = len([c for c in checks if c.matches])
    result.total_mismatched = len([c for c in checks if not c.matches and c.report_value is not None])
    result.total_missing = len([c for c in checks if c.report_value is None and c.actual_value is not None])
    return result


def _parse_number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _check_number(
    markdown: str,
    metric_name: str,
    actual: float,
    patterns: list[str],
    tolerance: float = 0.05,
    is_currency: bool = False,
) -> VerificationCheck:
    md_lower = markdown.lower()
    for pattern in patterns:
        match = re.search(pattern, md_lower)
        if match:
            report_val = _parse_number(match.group(1))
            if report_val is not None:
                if actual == 0:
                    matches = report_val == 0
                else:
                    matches = abs(report_val - actual) / max(abs(actual), 1) <= tolerance
                diff = abs(report_val - actual)
                pct = (diff / max(abs(actual), 1)) * 100
                note = "" if matches else f"Off by {diff:.1f} ({pct:.0f}%)"
                return VerificationCheck(
                    metric=metric_name,
                    report_value=report_val,
                    actual_value=actual,
                    matches=matches,
                    note=note,
                )

    return VerificationCheck(
        metric=metric_name,
        report_value=None,
        actual_value=actual,
        matches=False,
        note="Not found in report",
    )


def _check_text(markdown: str, metric_name: str, actual: str) -> VerificationCheck:
    found = actual.lower() in markdown.lower()
    return VerificationCheck(
        metric=metric_name,
        report_value=1.0 if found else 0.0,
        actual_value=1.0,
        matches=found,
        note="" if found else f"'{actual}' not mentioned in report",
    )

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sklearn.preprocessing import MinMaxScaler


MENU_BASELINE_PRICES = {
    "burger_combo": 12.00,
    "burrito_bowl": 10.50,
    "latte": 4.95,
}

MENU_LABELS = {
    "burger_combo": "Median Burger Combo",
    "burrito_bowl": "Median Burrito Bowl",
    "latte": "Median Latte",
}

JOB_SECTOR_LABELS = {
    "construction": "Construction Job Posts",
    "hospitality_service": "Hospitality/Service Job Posts",
    "retail": "Retail Job Posts",
}

JOB_BASELINE_SALARIES = {
    "construction": 80000.0,
    "hospitality_service": 42000.0,
    "retail": 38000.0,
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_scalar(value: float, lower: float, upper: float) -> float:
    scaler = MinMaxScaler(feature_range=(0, 100))
    frame = pd.DataFrame({"value": [lower, value, upper]})
    scaled = scaler.fit_transform(frame[["value"]]).ravel()
    return float(round(scaled[1], 2))


def _build_empty_summary(city: str) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc)
    return {
        "city": city,
        "observed_at": observed_at,
        "local_inflation_index": 100.0,
        "local_economic_heat_score": 0.0,
        "permit_indicators": [
            {"label": "Commercial Permits Scraped", "value": 0.0, "unit": "count"},
            {"label": "Issued Permit Rate", "value": 0.0, "unit": "percent"},
            {"label": "Average Permit Valuation", "value": 0.0, "unit": "usd"},
        ],
        "menu_indicators": [
            {"label": "Median Burger Combo", "value": 0.0, "unit": "usd"},
            {"label": "Median Burrito Bowl", "value": 0.0, "unit": "usd"},
            {"label": "Median Latte", "value": 0.0, "unit": "usd"},
        ],
        "job_indicators": [
            {"label": "Construction Job Posts", "value": 0.0, "unit": "count"},
            {"label": "Hospitality/Service Job Posts", "value": 0.0, "unit": "count"},
            {"label": "Retail Job Posts", "value": 0.0, "unit": "count"},
        ],
        "notes": [
            "No permit, menu, or jobs rows were available from the scraper payloads.",
            "Fallback baseline applied to preserve API availability.",
        ],
    }


def calculate_local_economic_summary(
    permit_payload: dict[str, Any],
    menu_payload: dict[str, Any],
    job_payload: dict[str, Any],
) -> dict[str, Any]:
    city = (
        permit_payload.get("city")
        or menu_payload.get("city")
        or job_payload.get("city")
        or "Unknown"
    )
    permit_frame = pd.DataFrame(permit_payload.get("records", []))
    menu_frame = pd.DataFrame(menu_payload.get("records", []))
    job_frame = pd.DataFrame(job_payload.get("records", []))

    if permit_frame.empty and menu_frame.empty and job_frame.empty:
        return _build_empty_summary(city)

    observed_candidates: list[datetime] = []

    if not permit_frame.empty:
        permit_frame["declared_value"] = permit_frame["declared_value"].apply(_safe_float)
        permit_frame["issued_date"] = pd.to_datetime(
            permit_frame["issued_date"], errors="coerce"
        )
        permit_frame["status_normalized"] = (
            permit_frame["status"].astype(str).str.strip().str.lower()
        )
        permit_frame["is_issued"] = permit_frame["status_normalized"].eq("issued").astype(int)

        valid_dates = permit_frame["issued_date"].dropna()
        if valid_dates.empty:
            permit_days_since_issue = pd.Series(
                [30.0] * len(permit_frame), dtype="float64"
            )
        else:
            latest_date = valid_dates.max()
            observed_candidates.append(
                latest_date.to_pydatetime().replace(tzinfo=timezone.utc)
            )
            permit_days_since_issue = (
                latest_date.normalize() - permit_frame["issued_date"].dt.normalize()
            ).dt.days.fillna(30)

        permit_frame["recency_weight"] = 1 / (
            1 + permit_days_since_issue.clip(lower=0)
        )
        permit_frame["weighted_value"] = (
            permit_frame["declared_value"] * permit_frame["recency_weight"]
        )

        permit_count = float(len(permit_frame))
        issued_rate = float(round(permit_frame["is_issued"].mean() * 100, 2))
        avg_valuation = float(round(permit_frame["declared_value"].mean(), 2))
        median_valuation = float(round(permit_frame["declared_value"].median(), 2))
        recent_weighted_value = float(round(permit_frame["weighted_value"].sum(), 2))
        project_diversity = float(permit_frame["project_type"].nunique())
    else:
        permit_count = 0.0
        issued_rate = 0.0
        avg_valuation = 0.0
        median_valuation = 0.0
        recent_weighted_value = 0.0
        project_diversity = 0.0

    if not menu_frame.empty:
        menu_frame["price"] = menu_frame["price"].apply(_safe_float)
        menu_baseline = pd.DataFrame(
            [
                {"benchmark_item": key, "baseline_price": value}
                for key, value in MENU_BASELINE_PRICES.items()
            ]
        )
        menu_frame = menu_frame.merge(menu_baseline, on="benchmark_item", how="left")
        menu_frame["baseline_price"] = menu_frame["baseline_price"].fillna(
            menu_frame["price"]
        )
        menu_frame["price_ratio"] = (
            menu_frame["price"] / menu_frame["baseline_price"].replace(0, 1)
        )
        menu_frame["price_delta_pct"] = (menu_frame["price_ratio"] - 1) * 100

        benchmark_prices = (
            menu_frame.groupby("benchmark_item", as_index=False)["price"].median()
        )
        benchmark_map = {
            row["benchmark_item"]: float(round(row["price"], 2))
            for _, row in benchmark_prices.iterrows()
        }

        avg_menu_price = float(round(menu_frame["price"].mean(), 2))
        menu_inflation_signal = float(round(menu_frame["price_delta_pct"].mean(), 2))
        benchmark_coverage = float(menu_frame["benchmark_item"].nunique())
    else:
        benchmark_map = {}
        avg_menu_price = 0.0
        menu_inflation_signal = 0.0
        benchmark_coverage = 0.0

    if not job_frame.empty:
        job_frame["salary_low"] = job_frame["salary_low"].apply(_safe_float)
        job_frame["salary_high"] = job_frame["salary_high"].apply(_safe_float)
        job_frame["salary_midpoint"] = job_frame["salary_midpoint"].apply(_safe_float)

        sector_counts_frame = job_frame.groupby("sector", as_index=False).agg(
            posting_count=("sector", "size"),
            median_salary=("salary_midpoint", "median"),
        )
        sector_counts = {
            row["sector"]: float(row["posting_count"])
            for _, row in sector_counts_frame.iterrows()
        }
        sector_salary_map = {
            row["sector"]: float(round(row["median_salary"], 2))
            for _, row in sector_counts_frame.iterrows()
        }

        merged_salary_frame = sector_counts_frame.merge(
            pd.DataFrame(
                [
                    {"sector": key, "baseline_salary": value}
                    for key, value in JOB_BASELINE_SALARIES.items()
                ]
            ),
            on="sector",
            how="left",
        )
        merged_salary_frame["salary_pressure_pct"] = (
            (
                merged_salary_frame["median_salary"]
                - merged_salary_frame["baseline_salary"]
            )
            / merged_salary_frame["baseline_salary"].replace(0, 1)
        ) * 100

        total_job_posts = float(len(job_frame))
        sector_coverage = float(job_frame["sector"].nunique())
        avg_salary_pressure = float(
            round(merged_salary_frame["salary_pressure_pct"].mean(), 2)
        )
        construction_posts = sector_counts.get("construction", 0.0)
        hospitality_posts = sector_counts.get("hospitality_service", 0.0)
        retail_posts = sector_counts.get("retail", 0.0)
    else:
        sector_counts = {}
        sector_salary_map = {}
        total_job_posts = 0.0
        sector_coverage = 0.0
        avg_salary_pressure = 0.0
        construction_posts = 0.0
        hospitality_posts = 0.0
        retail_posts = 0.0

    observed_timestamp = max(observed_candidates) if observed_candidates else datetime.now(
        timezone.utc
    )

    permit_pressure_score = (
        avg_valuation * 0.000015
        + median_valuation * 0.00001
        + permit_count * 0.18
        + issued_rate * 0.035
    )
    menu_pressure_score = max(menu_inflation_signal, 0) * 1.6 + avg_menu_price * 0.12
    combined_pressure = (permit_pressure_score * 0.65) + (menu_pressure_score * 0.35)
    local_inflation_index = round(100 + combined_pressure, 2)

    permit_heat_score = (
        _normalize_scalar(permit_count, 0, 50) * 0.25
        + _normalize_scalar(issued_rate, 0, 100) * 0.25
        + _normalize_scalar(recent_weighted_value, 0, 3_000_000) * 0.35
        + _normalize_scalar(project_diversity, 0, 12) * 0.15
    )
    menu_heat_score = (
        _normalize_scalar(menu_inflation_signal, 0, 25) * 0.6
        + _normalize_scalar(benchmark_coverage, 0, 3) * 0.4
    )
    jobs_heat_score = (
        _normalize_scalar(total_job_posts, 0, 40) * 0.45
        + _normalize_scalar(sector_coverage, 0, 3) * 0.2
        + _normalize_scalar(avg_salary_pressure, 0, 40) * 0.35
    )
    local_economic_heat_score = round(
        (permit_heat_score * 0.4)
        + (menu_heat_score * 0.25)
        + (jobs_heat_score * 0.35),
        2,
    )

    menu_indicators = []
    for benchmark_key in ("burger_combo", "burrito_bowl", "latte"):
        menu_indicators.append(
            {
                "label": MENU_LABELS[benchmark_key],
                "value": benchmark_map.get(benchmark_key, 0.0),
                "unit": "usd",
            }
        )
    menu_indicators.append(
        {
            "label": "Menu Price Inflation Signal",
            "value": menu_inflation_signal,
            "unit": "percent",
        }
    )

    job_indicators = []
    for sector_key in ("construction", "hospitality_service", "retail"):
        job_indicators.append(
            {
                "label": JOB_SECTOR_LABELS[sector_key],
                "value": sector_counts.get(sector_key, 0.0),
                "unit": "count",
            }
        )
    job_indicators.extend(
        [
            {
                "label": "Construction Median Salary",
                "value": sector_salary_map.get("construction", 0.0),
                "unit": "usd",
            },
            {
                "label": "Hospitality/Service Median Salary",
                "value": sector_salary_map.get("hospitality_service", 0.0),
                "unit": "usd",
            },
            {
                "label": "Retail Median Salary",
                "value": sector_salary_map.get("retail", 0.0),
                "unit": "usd",
            },
            {
                "label": "Total Local Job Posts",
                "value": total_job_posts,
                "unit": "count",
            },
            {
                "label": "Local Salary Pressure",
                "value": avg_salary_pressure,
                "unit": "percent",
            },
        ]
    )

    return {
        "city": city,
        "observed_at": observed_timestamp,
        "local_inflation_index": local_inflation_index,
        "local_economic_heat_score": local_economic_heat_score,
        "permit_indicators": [
            {
                "label": "Commercial Permits Scraped",
                "value": permit_count,
                "unit": "count",
            },
            {
                "label": "Issued Permit Rate",
                "value": issued_rate,
                "unit": "percent",
            },
            {
                "label": "Average Permit Valuation",
                "value": avg_valuation,
                "unit": "usd",
            },
            {
                "label": "Median Permit Valuation",
                "value": median_valuation,
                "unit": "usd",
            },
            {
                "label": "Recent Weighted Permit Value",
                "value": recent_weighted_value,
                "unit": "usd",
            },
        ],
        "menu_indicators": menu_indicators,
        "job_indicators": job_indicators,
        "notes": [
            "Commercial permit activity is scraper-backed.",
            "Restaurant menu prices are scraper-backed for burger combo, burrito bowl, and latte benchmarks.",
            "Local labor demand is scraper-backed for construction, hospitality/service, and retail.",
            "Inflation index blends permit pressure and menu price pressure.",
            "Economic heat score blends permit activity, menu-price shifts, and local job demand.",
        ],
    }

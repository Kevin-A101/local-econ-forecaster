from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.city_registry import (
    resolve_location,
    suggested_location_names,
    supported_city_names,
    supported_state_names,
)
from app.scrapers.job_scraper import scrape_local_jobs
from app.scrapers.menu_scraper import scrape_restaurant_menu
from app.scrapers.permit_scraper import scrape_commercial_permits
from app.services.economics_engine import calculate_local_economic_summary


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "app" / "static"
MODEL_VERSION = "mvp-full-backend-0.7.0"
TOTAL_SIGNALS = 3


class IndicatorPoint(BaseModel):
    label: str
    value: float
    unit: str


class SignalCoverage(BaseModel):
    signal: str
    available: bool
    record_count: int
    coverage_mode: str
    source_market: str


class ForecastSummary(BaseModel):
    city: str
    source_market: str
    coverage_mode: str
    coverage_label: str
    confidence_score: float = Field(..., ge=0, le=100)
    confidence_label: str
    available_signals: int = Field(..., ge=0, le=TOTAL_SIGNALS)
    total_signals: int = Field(default=TOTAL_SIGNALS, ge=TOTAL_SIGNALS, le=TOTAL_SIGNALS)
    signal_coverage: list[SignalCoverage]
    observed_at: datetime
    local_inflation_index: float = Field(..., ge=0)
    local_economic_heat_score: float = Field(..., ge=0, le=100)
    permits: list[IndicatorPoint]
    menu_prices: list[IndicatorPoint]
    jobs: list[IndicatorPoint]
    model_version: str
    notes: list[str]


class PermitRecord(BaseModel):
    permit_id: str
    project_type: str
    status: str
    issued_date: str
    address: str
    declared_value: float
    city: str
    source_url: str


class PermitScrapeResponse(BaseModel):
    city: str
    requested_market: str
    source_market: str
    coverage_mode: str
    source_url: str
    signal_available: bool
    record_count: int
    records: list[PermitRecord]


class MenuRecord(BaseModel):
    benchmark_item: str
    item_name: str
    item_description: str
    price: float
    city: str
    source_url: str


class MenuScrapeResponse(BaseModel):
    city: str
    requested_market: str
    source_market: str
    coverage_mode: str
    source_url: str
    signal_available: bool
    record_count: int
    records: list[MenuRecord]


class JobRecord(BaseModel):
    sector: str
    job_title: str
    sector_text: str
    company: str
    location: str
    salary_band: str
    salary_low: float
    salary_high: float
    salary_midpoint: float
    city: str
    source_url: str


class JobScrapeResponse(BaseModel):
    city: str
    requested_market: str
    source_market: str
    coverage_mode: str
    source_url: str
    signal_available: bool
    record_count: int
    records: list[JobRecord]


class SupportedLocationsResponse(BaseModel):
    cities: list[str]
    states: list[str]
    suggested_locations: list[str]
    default_location: str


app = FastAPI(
    title="Hyper-Local Business Cycle Forecaster",
    version="0.7.0",
    description=(
        "API for scraping hyper-local business signals and serving a live "
        "multi-city and statewide forecast summary dashboard."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _resolve_location_or_400(location: str | None):
    try:
        return resolve_location(location)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _confidence_from_payloads(*payloads: dict) -> dict:
    signal_names = ("permits", "menus", "jobs")
    coverage = []
    available_signals = 0
    coverage_modes = []

    for signal_name, payload in zip(signal_names, payloads, strict=True):
        available = bool(payload.get("signal_available"))
        available_signals += int(available)
        coverage_mode = str(payload.get("coverage_mode", "city"))
        coverage_modes.append(coverage_mode)
        coverage.append(
            SignalCoverage(
                signal=signal_name,
                available=available,
                record_count=int(payload.get("record_count", 0)),
                coverage_mode=coverage_mode,
                source_market=str(payload.get("source_market", payload.get("city", "Unknown"))),
            )
        )

    if "state_fallback" in coverage_modes:
        summary_mode = "state_fallback"
    elif "state" in coverage_modes:
        summary_mode = "state"
    else:
        summary_mode = "city"

    base_score = {
        "city": 96.0,
        "state": 84.0,
        "state_fallback": 74.0,
    }[summary_mode]
    confidence_score = max(30.0, round(base_score - ((TOTAL_SIGNALS - available_signals) * 18), 2))

    if available_signals == TOTAL_SIGNALS and summary_mode == "city":
        coverage_label = "Full city coverage"
        confidence_label = "High confidence"
    elif available_signals == TOTAL_SIGNALS and summary_mode == "state":
        coverage_label = "Statewide coverage"
        confidence_label = "Strong statewide signal"
    elif available_signals == TOTAL_SIGNALS:
        coverage_label = "City request resolved with state fallback"
        confidence_label = "Moderate confidence"
    else:
        coverage_label = f"Partial coverage ({available_signals}/{TOTAL_SIGNALS} signals)"
        confidence_label = "Directional only" if confidence_score < 65 else "Moderate confidence"

    first_payload = payloads[0]
    return {
        "source_market": str(first_payload.get("source_market", first_payload.get("city", "Unknown"))),
        "coverage_mode": summary_mode,
        "coverage_label": coverage_label,
        "confidence_score": confidence_score,
        "confidence_label": confidence_label,
        "available_signals": available_signals,
        "signal_coverage": coverage,
    }


async def build_live_summary(location: str | None = None) -> ForecastSummary:
    permit_payload = await scrape_commercial_permits(city=location)
    menu_payload = await scrape_restaurant_menu(city=location)
    job_payload = await scrape_local_jobs(city=location)
    engine_output = calculate_local_economic_summary(permit_payload, menu_payload, job_payload)
    coverage = _confidence_from_payloads(permit_payload, menu_payload, job_payload)

    notes = list(engine_output["notes"])
    notes.append(f"Location resolution: {coverage['coverage_label']}. Source market: {coverage['source_market']}.")
    if coverage["available_signals"] < TOTAL_SIGNALS:
        notes.append("One or more signals are unavailable, so the forecast is based on partial source coverage.")

    return ForecastSummary(
        city=engine_output["city"],
        source_market=coverage["source_market"],
        coverage_mode=coverage["coverage_mode"],
        coverage_label=coverage["coverage_label"],
        confidence_score=coverage["confidence_score"],
        confidence_label=coverage["confidence_label"],
        available_signals=coverage["available_signals"],
        signal_coverage=coverage["signal_coverage"],
        observed_at=engine_output["observed_at"],
        local_inflation_index=engine_output["local_inflation_index"],
        local_economic_heat_score=engine_output["local_economic_heat_score"],
        permits=[IndicatorPoint(**item) for item in engine_output["permit_indicators"]],
        menu_prices=[IndicatorPoint(**item) for item in engine_output["menu_indicators"]],
        jobs=[IndicatorPoint(**item) for item in engine_output["job_indicators"]],
        model_version=MODEL_VERSION,
        notes=notes,
    )


@app.get("/api/v1/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "hyper-local-business-cycle-forecaster",
        "version": app.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/locations", response_model=SupportedLocationsResponse, tags=["meta"])
async def get_supported_locations() -> SupportedLocationsResponse:
    return SupportedLocationsResponse(
        cities=supported_city_names(),
        states=supported_state_names(),
        suggested_locations=suggested_location_names(),
        default_location=resolve_location(None).display_name,
    )


@app.get("/api/v1/cities", response_model=SupportedLocationsResponse, tags=["meta"])
async def get_supported_cities_alias() -> SupportedLocationsResponse:
    return await get_supported_locations()


@app.get(
    "/api/v1/scrape/permits/commercial",
    response_model=PermitScrapeResponse,
    tags=["scraping"],
)
async def get_commercial_permits(
    city: str | None = Query(default=None, description="Any US state, supported city, or city/state input like Phoenix, AZ"),
) -> PermitScrapeResponse:
    _resolve_location_or_400(city)
    payload = await scrape_commercial_permits(city=city)
    return PermitScrapeResponse(**payload)


@app.get(
    "/api/v1/scrape/menu/restaurant",
    response_model=MenuScrapeResponse,
    tags=["scraping"],
)
async def get_restaurant_menu(
    city: str | None = Query(default=None, description="Any US state, supported city, or city/state input like Phoenix, AZ"),
) -> MenuScrapeResponse:
    _resolve_location_or_400(city)
    payload = await scrape_restaurant_menu(city=city)
    return MenuScrapeResponse(**payload)


@app.get(
    "/api/v1/scrape/jobs/local",
    response_model=JobScrapeResponse,
    tags=["scraping"],
)
async def get_local_jobs(
    city: str | None = Query(default=None, description="Any US state, supported city, or city/state input like Phoenix, AZ"),
) -> JobScrapeResponse:
    _resolve_location_or_400(city)
    payload = await scrape_local_jobs(city=city)
    return JobScrapeResponse(**payload)


@app.get("/api/v1/forecast/summary", response_model=ForecastSummary, tags=["forecast"])
async def get_forecast_summary(
    city: str | None = Query(default=None, description="Any US state, supported city, or city/state input like Phoenix, AZ"),
) -> ForecastSummary:
    _resolve_location_or_400(city)
    return await build_live_summary(location=city)


@app.get("/api/v1/forecast/debug", tags=["forecast"])
async def get_debug_payload(
    city: str | None = Query(default=None, description="Any US state, supported city, or city/state input like Phoenix, AZ"),
) -> JSONResponse:
    resolved_profile = _resolve_location_or_400(city)
    permit_scrape = await scrape_commercial_permits(city=city)
    menu_scrape = await scrape_restaurant_menu(city=city)
    job_scrape = await scrape_local_jobs(city=city)
    summary = await build_live_summary(location=city)

    return JSONResponse(
        content={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "requested_city": resolved_profile.display_name,
            "summary": summary.model_dump(mode="json"),
            "permit_scrape": permit_scrape,
            "menu_scrape": menu_scrape,
            "job_scrape": job_scrape,
        }
    )


@app.get("/", response_class=HTMLResponse)
async def serve_root() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))

    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>Hyper-Local Business Cycle Forecaster</title>
        </head>
        <body>
            <main>
                <h1>Hyper-Local Business Cycle Forecaster</h1>
                <p>The API is running.</p>
            </main>
        </body>
        </html>
        """.strip()
    )

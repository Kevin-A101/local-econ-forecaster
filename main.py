from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.scrapers.job_scraper import scrape_local_jobs
from app.scrapers.menu_scraper import scrape_restaurant_menu
from app.scrapers.permit_scraper import scrape_commercial_permits
from app.services.economics_engine import calculate_local_economic_summary


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "app" / "static"


class IndicatorPoint(BaseModel):
    label: str
    value: float
    unit: str


class ForecastSummary(BaseModel):
    city: str
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
    source_url: str
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
    source_url: str
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
    source_url: str
    record_count: int
    records: list[JobRecord]


async def build_live_summary() -> ForecastSummary:
    permit_payload = await scrape_commercial_permits()
    menu_payload = await scrape_restaurant_menu()
    job_payload = await scrape_local_jobs()
    engine_output = calculate_local_economic_summary(
        permit_payload, menu_payload, job_payload
    )

    return ForecastSummary(
        city=engine_output["city"],
        observed_at=engine_output["observed_at"],
        local_inflation_index=engine_output["local_inflation_index"],
        local_economic_heat_score=engine_output["local_economic_heat_score"],
        permits=[IndicatorPoint(**item) for item in engine_output["permit_indicators"]],
        menu_prices=[
            IndicatorPoint(**item) for item in engine_output["menu_indicators"]
        ],
        jobs=[IndicatorPoint(**item) for item in engine_output["job_indicators"]],
        model_version="mvp-full-backend-0.4.0",
        notes=engine_output["notes"],
    )


app = FastAPI(
    title="Hyper-Local Business Cycle Forecaster",
    version="0.4.0",
    description=(
        "MVP API for scraping hyper-local business signals and serving a lightweight "
        "forecast summary for a single dashboard."
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


@app.get("/api/v1/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "hyper-local-business-cycle-forecaster",
        "version": app.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get(
    "/api/v1/scrape/permits/commercial",
    response_model=PermitScrapeResponse,
    tags=["scraping"],
)
async def get_commercial_permits() -> PermitScrapeResponse:
    payload = await scrape_commercial_permits()
    return PermitScrapeResponse(**payload)


@app.get(
    "/api/v1/scrape/menu/restaurant",
    response_model=MenuScrapeResponse,
    tags=["scraping"],
)
async def get_restaurant_menu() -> MenuScrapeResponse:
    payload = await scrape_restaurant_menu()
    return MenuScrapeResponse(**payload)


@app.get(
    "/api/v1/scrape/jobs/local",
    response_model=JobScrapeResponse,
    tags=["scraping"],
)
async def get_local_jobs() -> JobScrapeResponse:
    payload = await scrape_local_jobs()
    return JobScrapeResponse(**payload)


@app.get("/api/v1/forecast/summary", response_model=ForecastSummary, tags=["forecast"])
async def get_forecast_summary() -> ForecastSummary:
    return await build_live_summary()


@app.get("/api/v1/forecast/debug", tags=["forecast"])
async def get_debug_payload() -> JSONResponse:
    permit_scrape = await scrape_commercial_permits()
    menu_scrape = await scrape_restaurant_menu()
    job_scrape = await scrape_local_jobs()
    summary = calculate_local_economic_summary(
        permit_scrape, menu_scrape, job_scrape
    )

    return JSONResponse(
        content={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": ForecastSummary(
                city=summary["city"],
                observed_at=summary["observed_at"],
                local_inflation_index=summary["local_inflation_index"],
                local_economic_heat_score=summary["local_economic_heat_score"],
                permits=[IndicatorPoint(**item) for item in summary["permit_indicators"]],
                menu_prices=[IndicatorPoint(**item) for item in summary["menu_indicators"]],
                jobs=[IndicatorPoint(**item) for item in summary["job_indicators"]],
                model_version="mvp-full-backend-0.4.0",
                notes=summary["notes"],
            ).model_dump(mode="json"),
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
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                    background: #0f172a;
                    color: #e2e8f0;
                    margin: 0;
                    display: grid;
                    min-height: 100vh;
                    place-items: center;
                    padding: 24px;
                }
                main {
                    max-width: 720px;
                    line-height: 1.6;
                }
                code {
                    background: rgba(148, 163, 184, 0.15);
                    padding: 2px 6px;
                    border-radius: 6px;
                }
            </style>
        </head>
        <body>
            <main>
                <h1>Hyper-Local Business Cycle Forecaster</h1>
                <p>The API is running. The dashboard HTML will be added in the next step.</p>
                <p>Try <code>/api/v1/scrape/permits/commercial</code>, <code>/api/v1/scrape/menu/restaurant</code>, <code>/api/v1/scrape/jobs/local</code>, or <code>/api/v1/forecast/summary</code>.</p>
            </main>
        </body>
        </html>
        """.strip()
    )


def get_openapi_tags() -> list[dict[str, Any]]:
    return [
        {"name": "health", "description": "Service availability endpoints."},
        {"name": "scraping", "description": "Web scraping endpoints for local indicators."},
        {"name": "forecast", "description": "Forecast and local indicator endpoints."},
    ]


app.openapi_tags = get_openapi_tags()

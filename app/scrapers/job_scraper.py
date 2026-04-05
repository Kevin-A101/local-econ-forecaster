from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright._impl._errors import Error as PlaywrightError

from app.city_registry import resolve_location


SECTOR_PATTERNS = {
    "construction": re.compile(r"\bconstruction\b|\bsuperintendent\b|\bproject manager\b|\bestimator\b|\bproject engineer\b", re.I),
    "hospitality_service": re.compile(
        r"\bhospitality\b|\bservice\b|\brestaurant\b|\bbarista\b|\bserver\b|\bcafe\b|\boperations\b",
        re.I,
    ),
    "retail": re.compile(r"\bretail\b|\bsales associate\b|\bstore\b|\bfloor supervisor\b|\bexperience supervisor\b", re.I),
}


@dataclass
class JobPortalConfig:
    city: str
    source_market: str
    coverage_mode: str
    source_url: str
    mock_html: str
    card_selector: str = "[data-testid='job-card']"
    page_ready_selector: str = "[data-testid='job-results']"
    title_selector: str = "[data-testid='job-title']"
    sector_selector: str = "[data-testid='job-sector']"
    company_selector: str = "[data-testid='job-company']"
    location_selector: str = "[data-testid='job-location']"
    salary_selector: str = "[data-testid='job-salary']"
    timeout_ms: int = 30_000
    headless: bool = True


def build_jobs_config(city_query: Optional[str] = None) -> JobPortalConfig:
    profile = resolve_location(city_query)
    return JobPortalConfig(
        city=profile.display_name,
        source_market=profile.source_market,
        coverage_mode=profile.coverage_mode,
        source_url=profile.jobs_source_url,
        mock_html=profile.jobs_html,
    )


def _classify_sector(title: str, sector_text: str) -> Optional[str]:
    combined = f"{title} {sector_text}".strip()
    for sector, pattern in SECTOR_PATTERNS.items():
        if pattern.search(combined):
            return sector
    return None


def _parse_salary_band(value: str) -> tuple[float, float]:
    numbers = [float(match.replace(",", "")) for match in re.findall(r"\d[\d,]*\.?\d*", value)]
    if not numbers:
        return 0.0, 0.0

    if len(numbers) == 1:
        return numbers[0], numbers[0]

    low, high = numbers[0], numbers[1]
    if max(low, high) <= 500:
        low *= 2080
        high *= 2080
    return low, high


def _extract_rows_from_html(html: str, config: JobPortalConfig) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for card in soup.select(config.card_selector):
        title_node = card.select_one(config.title_selector)
        sector_node = card.select_one(config.sector_selector)
        company_node = card.select_one(config.company_selector)
        location_node = card.select_one(config.location_selector)
        salary_node = card.select_one(config.salary_selector)
        rows.append(
            {
                "job_title": title_node.get_text(strip=True) if title_node else "",
                "sector_text": sector_node.get_text(strip=True) if sector_node else "",
                "company": company_node.get_text(strip=True) if company_node else "",
                "location": location_node.get_text(strip=True) if location_node else "",
                "salary_band": salary_node.get_text(strip=True) if salary_node else "",
            }
        )
    return rows


async def scrape_local_jobs(
    city: Optional[str] = None,
    config: Optional[JobPortalConfig] = None,
) -> dict[str, Any]:
    config = config or build_jobs_config(city)
    rows: list[dict[str, str]] = []

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.headless)
            page = await browser.new_page()

            try:
                if config.source_url.startswith("mock://"):
                    await page.set_content(config.mock_html)
                else:
                    await page.goto(config.source_url, wait_until="domcontentloaded")

                await page.wait_for_selector(
                    config.page_ready_selector,
                    timeout=config.timeout_ms,
                )

                rows = await page.locator(config.card_selector).evaluate_all(
                    f"""
                    (elements) => elements.map((card) => {{
                        const getText = (selector) => {{
                            const node = card.querySelector(selector);
                            return node ? node.innerText.trim() : "";
                        }};

                        return {{
                            job_title: getText("{config.title_selector}"),
                            sector_text: getText("{config.sector_selector}"),
                            company: getText("{config.company_selector}"),
                            location: getText("{config.location_selector}"),
                            salary_band: getText("{config.salary_selector}"),
                        }};
                    }})
                    """
                )
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(
                    f"Timed out while waiting for job selector '{config.page_ready_selector}'"
                ) from exc
            finally:
                await browser.close()
    except PlaywrightError:
        if config.source_url.startswith("mock://"):
            rows = _extract_rows_from_html(config.mock_html, config)
        else:
            raise

    normalized_rows = []
    for row in rows:
        job_title = row["job_title"].strip()
        sector_text = row["sector_text"].strip()
        normalized_sector = _classify_sector(job_title, sector_text)
        if not normalized_sector:
            continue

        salary_low, salary_high = _parse_salary_band(row["salary_band"])
        normalized_rows.append(
            {
                "sector": normalized_sector,
                "job_title": job_title,
                "sector_text": sector_text,
                "company": row["company"].strip(),
                "location": row["location"].strip(),
                "salary_band": row["salary_band"].strip(),
                "salary_low": salary_low,
                "salary_high": salary_high,
                "salary_midpoint": round((salary_low + salary_high) / 2, 2),
                "city": config.city,
                "source_url": config.source_url,
            }
        )

    return {
        "city": config.city,
        "requested_market": config.city,
        "source_market": config.source_market,
        "coverage_mode": config.coverage_mode,
        "source_url": config.source_url,
        "signal_available": bool(normalized_rows),
        "record_count": len(normalized_rows),
        "records": normalized_rows,
    }

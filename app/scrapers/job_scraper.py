from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright._impl._errors import Error as PlaywrightError


MOCK_JOBS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Mock Local Jobs</title>
</head>
<body>
    <main>
        <section data-testid="job-results">
            <article data-testid="job-card">
                <h2 data-testid="job-title">Commercial Construction Project Manager</h2>
                <p data-testid="job-sector">Construction</p>
                <p data-testid="job-company">North Texas Build Group</p>
                <p data-testid="job-location">Frisco, TX</p>
                <p data-testid="job-salary">$88,000 - $112,000</p>
            </article>
            <article data-testid="job-card">
                <h2 data-testid="job-title">Assistant Superintendent</h2>
                <p data-testid="job-sector">Construction</p>
                <p data-testid="job-company">Legacy Commercial Builders</p>
                <p data-testid="job-location">Plano, TX</p>
                <p data-testid="job-salary">$72,000 - $91,000</p>
            </article>
            <article data-testid="job-card">
                <h2 data-testid="job-title">Restaurant General Manager</h2>
                <p data-testid="job-sector">Hospitality</p>
                <p data-testid="job-company">Preston Corridor Kitchen</p>
                <p data-testid="job-location">Frisco, TX</p>
                <p data-testid="job-salary">$58,000 - $74,000</p>
            </article>
            <article data-testid="job-card">
                <h2 data-testid="job-title">Barista Shift Lead</h2>
                <p data-testid="job-sector">Service</p>
                <p data-testid="job-company">Oak Street Coffee</p>
                <p data-testid="job-location">Frisco, TX</p>
                <p data-testid="job-salary">$18 - $22</p>
            </article>
            <article data-testid="job-card">
                <h2 data-testid="job-title">Retail Store Supervisor</h2>
                <p data-testid="job-sector">Retail</p>
                <p data-testid="job-company">Stonebriar Outfitters</p>
                <p data-testid="job-location">Frisco, TX</p>
                <p data-testid="job-salary">$44,000 - $52,000</p>
            </article>
            <article data-testid="job-card">
                <h2 data-testid="job-title">Retail Sales Associate</h2>
                <p data-testid="job-sector">Retail</p>
                <p data-testid="job-company">Legacy Home Goods</p>
                <p data-testid="job-location">Plano, TX</p>
                <p data-testid="job-salary">$16 - $19</p>
            </article>
        </section>
    </main>
</body>
</html>
""".strip()


SECTOR_PATTERNS = {
    "construction": re.compile(r"\bconstruction\b|\bsuperintendent\b|\bproject manager\b", re.I),
    "hospitality_service": re.compile(
        r"\bhospitality\b|\bservice\b|\brestaurant\b|\bbarista\b|\bserver\b|\bcafe\b",
        re.I,
    ),
    "retail": re.compile(r"\bretail\b|\bsales associate\b|\bstore\b", re.I),
}


@dataclass
class JobPortalConfig:
    city: str = "Frisco, TX"
    source_url: str = os.getenv("LOCAL_JOBS_URL", "mock://frisco-local-jobs")
    card_selector: str = "[data-testid='job-card']"
    page_ready_selector: str = "[data-testid='job-results']"
    title_selector: str = "[data-testid='job-title']"
    sector_selector: str = "[data-testid='job-sector']"
    company_selector: str = "[data-testid='job-company']"
    location_selector: str = "[data-testid='job-location']"
    salary_selector: str = "[data-testid='job-salary']"
    timeout_ms: int = 30_000
    headless: bool = True


def _classify_sector(title: str, sector_text: str) -> str | None:
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


async def scrape_local_jobs(config: JobPortalConfig | None = None) -> dict[str, Any]:
    config = config or JobPortalConfig()
    rows = []

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.headless)
            page = await browser.new_page()

            try:
                if config.source_url.startswith("mock://"):
                    await page.set_content(MOCK_JOBS_HTML)
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
                    f"Timed out while waiting for job selector "
                    f"'{config.page_ready_selector}'"
                ) from exc
            finally:
                await browser.close()
    except PlaywrightError:
        if config.source_url.startswith("mock://"):
            rows = _extract_rows_from_html(MOCK_JOBS_HTML, config)
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
        "source_url": config.source_url,
        "record_count": len(normalized_rows),
        "records": normalized_rows,
    }

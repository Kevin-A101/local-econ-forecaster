from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright._impl._errors import Error as PlaywrightError

from app.city_registry import resolve_location


@dataclass
class PermitPortalConfig:
    city: str
    source_market: str
    coverage_mode: str
    source_url: str
    mock_html: str
    table_selector: str = "table[data-testid='permit-results']"
    row_selector: str = "tbody tr"
    page_ready_selector: str = "table[data-testid='permit-results']"
    timeout_ms: int = 30_000
    headless: bool = True


def build_permit_config(city_query: Optional[str] = None) -> PermitPortalConfig:
    profile = resolve_location(city_query)
    return PermitPortalConfig(
        city=profile.display_name,
        source_market=profile.source_market,
        coverage_mode=profile.coverage_mode,
        source_url=profile.permits_source_url,
        mock_html=profile.permits_html,
    )


def _parse_currency(value: str) -> float:
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    return float(cleaned) if cleaned else 0.0


def _parse_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""

    known_formats = ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y")
    for fmt in known_formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def _extract_rows_from_html(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for row in soup.select("table[data-testid='permit-results'] tbody tr"):
        cells = [cell.get_text(strip=True) for cell in row.select("td, th")]
        rows.append(
            {
                "permit_id": cells[0] if len(cells) > 0 else "",
                "project_type": cells[1] if len(cells) > 1 else "",
                "status": cells[2] if len(cells) > 2 else "",
                "issued_date": cells[3] if len(cells) > 3 else "",
                "address": cells[4] if len(cells) > 4 else "",
                "declared_value": cells[5] if len(cells) > 5 else "",
            }
        )
    return rows


async def scrape_commercial_permits(
    city: Optional[str] = None,
    config: Optional[PermitPortalConfig] = None,
) -> dict[str, Any]:
    config = config or build_permit_config(city)
    rows: list[dict[str, str]] = []

    if config.source_url.startswith("mock://"):
        rows = _extract_rows_from_html(config.mock_html)
    else:
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=config.headless)
                page = await browser.new_page()

                try:
                    await page.goto(config.source_url, wait_until="domcontentloaded")
                    await page.wait_for_selector(
                        config.page_ready_selector,
                        timeout=config.timeout_ms,
                    )

                    rows = await page.locator(
                        f"{config.table_selector} {config.row_selector}"
                    ).evaluate_all(
                        """
                        (elements) => elements.map((row) => {
                            const cells = Array.from(row.querySelectorAll("td, th"))
                                .map((cell) => cell.innerText.trim());
                            return {
                                permit_id: cells[0] ?? "",
                                project_type: cells[1] ?? "",
                                status: cells[2] ?? "",
                                issued_date: cells[3] ?? "",
                                address: cells[4] ?? "",
                                declared_value: cells[5] ?? "",
                            };
                        })
                        """
                    )
                except PlaywrightTimeoutError as exc:
                    raise RuntimeError(
                        f"Timed out while waiting for permit portal selector '{config.page_ready_selector}'"
                    ) from exc
                finally:
                    await browser.close()
        except PlaywrightError:
            raise

    normalized_rows = [
        {
            "permit_id": row["permit_id"].strip(),
            "project_type": row["project_type"].strip(),
            "status": row["status"].strip(),
            "issued_date": _parse_date(row["issued_date"]),
            "address": row["address"].strip(),
            "declared_value": _parse_currency(row["declared_value"]),
            "city": config.city,
            "source_url": config.source_url,
        }
        for row in rows
    ]

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

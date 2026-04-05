from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright._impl._errors import Error as PlaywrightError


MOCK_PERMIT_PORTAL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Mock Commercial Permits</title>
</head>
<body>
    <main>
        <h1>Commercial Permit Search Results</h1>
        <table data-testid="permit-results">
            <thead>
                <tr>
                    <th>Permit ID</th>
                    <th>Project Type</th>
                    <th>Status</th>
                    <th>Issued Date</th>
                    <th>Address</th>
                    <th>Declared Value</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>CP-2026-00081</td>
                    <td>Shell Building</td>
                    <td>Issued</td>
                    <td>2026-03-29</td>
                    <td>12501 Dallas Pkwy</td>
                    <td>$1,245,000</td>
                </tr>
                <tr>
                    <td>CP-2026-00079</td>
                    <td>Restaurant Finish-Out</td>
                    <td>Issued</td>
                    <td>2026-03-27</td>
                    <td>8990 Preston Rd</td>
                    <td>$318,500</td>
                </tr>
                <tr>
                    <td>CP-2026-00075</td>
                    <td>Medical Office Renovation</td>
                    <td>Issued</td>
                    <td>2026-03-21</td>
                    <td>8455 Warren Pkwy</td>
                    <td>$642,250</td>
                </tr>
                <tr>
                    <td>CP-2026-00070</td>
                    <td>Retail Interior Finish-Out</td>
                    <td>Issued</td>
                    <td>2026-03-16</td>
                    <td>2601 Network Blvd</td>
                    <td>$284,900</td>
                </tr>
                <tr>
                    <td>CP-2026-00063</td>
                    <td>Warehouse Expansion</td>
                    <td>Under Review</td>
                    <td>2026-03-10</td>
                    <td>11000 Research Rd</td>
                    <td>$2,180,000</td>
                </tr>
                <tr>
                    <td>CP-2026-00054</td>
                    <td>Hotel Renovation</td>
                    <td>Issued</td>
                    <td>2026-03-04</td>
                    <td>4343 Legacy Dr</td>
                    <td>$905,400</td>
                </tr>
            </tbody>
        </table>
    </main>
</body>
</html>
""".strip()


@dataclass
class PermitPortalConfig:
    city: str = "Frisco, TX"
    source_url: str = os.getenv(
        "COMMERCIAL_PERMITS_URL", "mock://frisco-commercial-permits"
    )
    table_selector: str = "table[data-testid='permit-results']"
    row_selector: str = "tbody tr"
    page_ready_selector: str = "table[data-testid='permit-results']"
    timeout_ms: int = 30_000
    headless: bool = True


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
    config: PermitPortalConfig | None = None,
) -> dict[str, Any]:
    config = config or PermitPortalConfig()
    rows = []

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.headless)
            page = await browser.new_page()

            try:
                if config.source_url.startswith("mock://"):
                    await page.set_content(MOCK_PERMIT_PORTAL_HTML)
                else:
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
                    f"Timed out while waiting for permit portal selector "
                    f"'{config.page_ready_selector}'"
                ) from exc
            finally:
                await browser.close()
    except PlaywrightError:
        if config.source_url.startswith("mock://"):
            rows = _extract_rows_from_html(MOCK_PERMIT_PORTAL_HTML)
        else:
            raise

    normalized_rows = []
    for row in rows:
        normalized_rows.append(
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
        )

    return {
        "city": config.city,
        "source_url": config.source_url,
        "record_count": len(normalized_rows),
        "records": normalized_rows,
    }

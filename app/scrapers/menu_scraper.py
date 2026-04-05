from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright._impl._errors import Error as PlaywrightError

from app.city_registry import resolve_location


BENCHMARK_PATTERNS = {
    "burger_combo": re.compile(r"\bburger\b.*\bcombo\b|\bcombo\b.*\bburger\b", re.I),
    "burrito_bowl": re.compile(r"\bburrito\b.*\bbowl\b|\bbowl\b.*\bburrito\b", re.I),
    "latte": re.compile(r"\blatte\b", re.I),
}


@dataclass
class MenuPortalConfig:
    city: str
    source_market: str
    coverage_mode: str
    source_url: str
    mock_html: str
    item_selector: str = "[data-testid='menu-item']"
    page_ready_selector: str = "[data-testid='menu-list']"
    name_selector: str = "[data-testid='item-name']"
    description_selector: str = "[data-testid='item-description']"
    price_selector: str = "[data-testid='item-price']"
    timeout_ms: int = 30_000
    headless: bool = True


def build_menu_config(city_query: Optional[str] = None) -> MenuPortalConfig:
    profile = resolve_location(city_query)
    return MenuPortalConfig(
        city=profile.display_name,
        source_market=profile.source_market,
        coverage_mode=profile.coverage_mode,
        source_url=profile.menu_source_url,
        mock_html=profile.menu_html,
    )


def _parse_currency(value: str) -> float:
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    return float(cleaned) if cleaned else 0.0


def _classify_benchmark_item(name: str, description: str) -> Optional[str]:
    combined = f"{name} {description}".strip()
    for benchmark, pattern in BENCHMARK_PATTERNS.items():
        if pattern.search(combined):
            return benchmark
    return None


def _extract_rows_from_html(html: str, config: MenuPortalConfig) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for item in soup.select(config.item_selector):
        name_node = item.select_one(config.name_selector)
        description_node = item.select_one(config.description_selector)
        price_node = item.select_one(config.price_selector)
        rows.append(
            {
                "item_name": name_node.get_text(strip=True) if name_node else "",
                "item_description": description_node.get_text(strip=True) if description_node else "",
                "price": price_node.get_text(strip=True) if price_node else "",
            }
        )
    return rows


async def scrape_restaurant_menu(
    city: Optional[str] = None,
    config: Optional[MenuPortalConfig] = None,
) -> dict[str, Any]:
    config = config or build_menu_config(city)
    rows: list[dict[str, str]] = []

    if config.source_url.startswith("mock://"):
        rows = _extract_rows_from_html(config.mock_html, config)
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

                    rows = await page.locator(config.item_selector).evaluate_all(
                        f"""
                        (elements) => elements.map((item) => {{
                            const getText = (selector) => {{
                                const node = item.querySelector(selector);
                                return node ? node.innerText.trim() : "";
                            }};

                            return {{
                                item_name: getText("{config.name_selector}"),
                                item_description: getText("{config.description_selector}"),
                                price: getText("{config.price_selector}"),
                            }};
                        }})
                        """
                    )
                except PlaywrightTimeoutError as exc:
                    raise RuntimeError(
                        f"Timed out while waiting for menu selector '{config.page_ready_selector}'"
                    ) from exc
                finally:
                    await browser.close()
        except PlaywrightError:
            raise

    normalized_rows = []
    for row in rows:
        item_name = row["item_name"].strip()
        item_description = row["item_description"].strip()
        benchmark_item = _classify_benchmark_item(item_name, item_description)
        if not benchmark_item:
            continue

        normalized_rows.append(
            {
                "benchmark_item": benchmark_item,
                "item_name": item_name,
                "item_description": item_description,
                "price": _parse_currency(row["price"]),
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

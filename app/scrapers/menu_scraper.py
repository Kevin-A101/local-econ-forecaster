from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright._impl._errors import Error as PlaywrightError


MOCK_MENU_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>Mock Local Menu</title>
</head>
<body>
    <main>
        <section data-testid="menu-list">
            <article data-testid="menu-item">
                <h2 data-testid="item-name">Signature Burger Combo</h2>
                <p data-testid="item-description">Double patty burger, fries, and a fountain drink.</p>
                <span data-testid="item-price">$13.95</span>
            </article>
            <article data-testid="menu-item">
                <h2 data-testid="item-name">Chicken Burrito Bowl</h2>
                <p data-testid="item-description">Rice, beans, salsa, pico, and grilled chicken.</p>
                <span data-testid="item-price">$12.45</span>
            </article>
            <article data-testid="menu-item">
                <h2 data-testid="item-name">Vanilla Latte</h2>
                <p data-testid="item-description">Espresso with steamed milk and vanilla.</p>
                <span data-testid="item-price">$5.85</span>
            </article>
            <article data-testid="menu-item">
                <h2 data-testid="item-name">Crispy Chicken Sandwich</h2>
                <p data-testid="item-description">Buttermilk fried chicken with slaw.</p>
                <span data-testid="item-price">$11.95</span>
            </article>
        </section>
    </main>
</body>
</html>
""".strip()


BENCHMARK_PATTERNS = {
    "burger_combo": re.compile(r"\bburger\b.*\bcombo\b|\bcombo\b.*\bburger\b", re.I),
    "burrito_bowl": re.compile(r"\bburrito\b.*\bbowl\b|\bbowl\b.*\bburrito\b", re.I),
    "latte": re.compile(r"\blatte\b", re.I),
}


@dataclass
class MenuPortalConfig:
    city: str = "Frisco, TX"
    source_url: str = os.getenv("RESTAURANT_MENU_URL", "mock://frisco-restaurant-menu")
    item_selector: str = "[data-testid='menu-item']"
    page_ready_selector: str = "[data-testid='menu-list']"
    name_selector: str = "[data-testid='item-name']"
    description_selector: str = "[data-testid='item-description']"
    price_selector: str = "[data-testid='item-price']"
    timeout_ms: int = 30_000
    headless: bool = True


def _parse_currency(value: str) -> float:
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    return float(cleaned) if cleaned else 0.0


def _classify_benchmark_item(name: str, description: str) -> str | None:
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
                "item_description": (
                    description_node.get_text(strip=True) if description_node else ""
                ),
                "price": price_node.get_text(strip=True) if price_node else "",
            }
        )
    return rows


async def scrape_restaurant_menu(
    config: MenuPortalConfig | None = None,
) -> dict[str, Any]:
    config = config or MenuPortalConfig()
    rows = []

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.headless)
            page = await browser.new_page()

            try:
                if config.source_url.startswith("mock://"):
                    await page.set_content(MOCK_MENU_HTML)
                else:
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
                    f"Timed out while waiting for menu selector "
                    f"'{config.page_ready_selector}'"
                ) from exc
            finally:
                await browser.close()
    except PlaywrightError:
        if config.source_url.startswith("mock://"):
            rows = _extract_rows_from_html(MOCK_MENU_HTML, config)
        else:
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
        "source_url": config.source_url,
        "record_count": len(normalized_rows),
        "records": normalized_rows,
    }

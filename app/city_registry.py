from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LocationProfile:
    slug: str
    display_name: str
    aliases: tuple[str, ...]
    permits_source_url: str
    menu_source_url: str
    jobs_source_url: str
    permits_html: str
    menu_html: str
    jobs_html: str
    source_market: str
    state_code: str
    state_name: str
    coverage_mode: str


STATE_METADATA: dict[str, tuple[str, str]] = {
    "AL": ("Alabama", "Birmingham"),
    "AK": ("Alaska", "Anchorage"),
    "AZ": ("Arizona", "Phoenix"),
    "AR": ("Arkansas", "Little Rock"),
    "CA": ("California", "Los Angeles"),
    "CO": ("Colorado", "Denver"),
    "CT": ("Connecticut", "Hartford"),
    "DE": ("Delaware", "Wilmington"),
    "FL": ("Florida", "Miami"),
    "GA": ("Georgia", "Atlanta"),
    "HI": ("Hawaii", "Honolulu"),
    "ID": ("Idaho", "Boise"),
    "IL": ("Illinois", "Chicago"),
    "IN": ("Indiana", "Indianapolis"),
    "IA": ("Iowa", "Des Moines"),
    "KS": ("Kansas", "Wichita"),
    "KY": ("Kentucky", "Louisville"),
    "LA": ("Louisiana", "New Orleans"),
    "ME": ("Maine", "Portland"),
    "MD": ("Maryland", "Baltimore"),
    "MA": ("Massachusetts", "Boston"),
    "MI": ("Michigan", "Detroit"),
    "MN": ("Minnesota", "Minneapolis"),
    "MS": ("Mississippi", "Jackson"),
    "MO": ("Missouri", "Kansas City"),
    "MT": ("Montana", "Billings"),
    "NE": ("Nebraska", "Omaha"),
    "NV": ("Nevada", "Las Vegas"),
    "NH": ("New Hampshire", "Manchester"),
    "NJ": ("New Jersey", "Newark"),
    "NM": ("New Mexico", "Albuquerque"),
    "NY": ("New York", "New York City"),
    "NC": ("North Carolina", "Charlotte"),
    "ND": ("North Dakota", "Fargo"),
    "OH": ("Ohio", "Columbus"),
    "OK": ("Oklahoma", "Oklahoma City"),
    "OR": ("Oregon", "Portland"),
    "PA": ("Pennsylvania", "Philadelphia"),
    "RI": ("Rhode Island", "Providence"),
    "SC": ("South Carolina", "Charleston"),
    "SD": ("South Dakota", "Sioux Falls"),
    "TN": ("Tennessee", "Nashville"),
    "TX": ("Texas", "Dallas"),
    "UT": ("Utah", "Salt Lake City"),
    "VT": ("Vermont", "Burlington"),
    "VA": ("Virginia", "Richmond"),
    "WA": ("Washington", "Seattle"),
    "WV": ("West Virginia", "Charleston"),
    "WI": ("Wisconsin", "Milwaukee"),
    "WY": ("Wyoming", "Cheyenne"),
}


def _normalize_city(value: str) -> str:
    return " ".join(value.lower().replace(",", " ").split())


def _stable_int(key: str, minimum: int, maximum: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    span = maximum - minimum + 1
    return minimum + (int(digest[:8], 16) % span)


def _titleize_location(value: str) -> str:
    minor_words = {"and", "of", "the"}
    parts = []
    for token in value.replace("-", " ").split():
        lowered = token.lower()
        if lowered in {"st", "st.", "ft", "ft."}:
            parts.append(lowered.replace(".", "").title())
        elif lowered in minor_words and parts:
            parts.append(lowered)
        else:
            parts.append(lowered.capitalize())
    return " ".join(parts)


def _state_aliases(state_name: str, state_code: str) -> tuple[str, ...]:
    return (
        state_name,
        state_name.lower(),
        state_code,
        state_code.lower(),
        f"{state_name} state",
        f"{state_code} state",
    )


def _state_slug(state_code: str) -> str:
    return state_code.lower()


def _generate_permits_html(market_name: str, state_code: str, anchor_city: str) -> str:
    project_types = [
        "Mixed-Use Redevelopment",
        "Restaurant Interior Build-Out",
        "Medical Office Finish-Out",
        "Warehouse Expansion",
        "Hotel Amenity Refresh",
        "Retail Streetscape Upgrade",
    ]
    rows = []
    for index, project_type in enumerate(project_types, start=1):
        declared_value = _stable_int(f"{state_code}-permit-{index}", 240, 3480) * 1000
        day = 31 - (index * 4)
        permit_id = f"{state_code}-2026-{_stable_int(f'{state_code}-id-{index}', 210, 980):04d}"
        address_number = _stable_int(f"{state_code}-addr-{index}", 110, 9400)
        street = [
            "Main St",
            "Market Ave",
            "Commerce Blvd",
            "Riverside Dr",
            "Oak St",
            "Central Ave",
        ][index - 1]
        status = "Issued" if index != 4 else "Under Review"
        rows.append(
            f"<tr><td>{permit_id}</td><td>{project_type}</td><td>{status}</td><td>2026-03-{day:02d}</td><td>{address_number} {street}, {anchor_city}</td><td>${declared_value:,.0f}</td></tr>"
        )

    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\" />"
        f"<title>{market_name} Commercial Permits</title></head><body><main>"
        "<table data-testid=\"permit-results\"><tbody>"
        + "".join(rows)
        + "</tbody></table></main></body></html>"
    )


def _generate_menu_html(market_name: str, state_code: str) -> str:
    burger_price = _stable_int(f"{state_code}-burger", 1295, 1645) / 100
    burrito_price = _stable_int(f"{state_code}-burrito", 1115, 1455) / 100
    latte_price = _stable_int(f"{state_code}-latte", 525, 745) / 100
    sandwich_price = _stable_int(f"{state_code}-sandwich", 1185, 1495) / 100

    return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" /><title>{market_name} Menu</title></head>
<body>
    <main>
        <section data-testid="menu-list">
            <article data-testid="menu-item"><h2 data-testid="item-name">Signature Burger Combo</h2><p data-testid="item-description">Double burger combo with fries and drink.</p><span data-testid="item-price">${burger_price:.2f}</span></article>
            <article data-testid="menu-item"><h2 data-testid="item-name">Chicken Burrito Bowl</h2><p data-testid="item-description">Rice, beans, salsa, and grilled chicken.</p><span data-testid="item-price">${burrito_price:.2f}</span></article>
            <article data-testid="menu-item"><h2 data-testid="item-name">Vanilla Latte</h2><p data-testid="item-description">Espresso with steamed milk and vanilla.</p><span data-testid="item-price">${latte_price:.2f}</span></article>
            <article data-testid="menu-item"><h2 data-testid="item-name">Crispy Chicken Sandwich</h2><p data-testid="item-description">House chicken sandwich with pickles.</p><span data-testid="item-price">${sandwich_price:.2f}</span></article>
        </section>
    </main>
</body>
</html>
""".strip()


def _generate_jobs_html(market_name: str, state_code: str, anchor_city: str) -> str:
    roles = [
        ("Commercial Project Manager", "Construction", "Northline Builders"),
        ("Assistant Superintendent", "Construction", "Regional Development Group"),
        ("Restaurant General Manager", "Hospitality", "Main Street Dining Co"),
        ("Barista Shift Lead", "Service", "Signal Coffee House"),
        ("Retail Operations Supervisor", "Retail", "Local Merchants Collective"),
        ("Retail Sales Associate", "Retail", "Neighborhood Goods Market"),
    ]
    cards = []
    for index, (title, sector, company) in enumerate(roles, start=1):
        low = _stable_int(f"{state_code}-salary-low-{index}", 18, 108)
        high = low + _stable_int(f"{state_code}-salary-high-{index}", 4, 28)
        if low < 40:
            salary_band = f"${low} - ${high}"
        else:
            salary_band = f"${low * 1000:,.0f} - ${high * 1000:,.0f}"
        cards.append(
            f"<article data-testid=\"job-card\"><h2 data-testid=\"job-title\">{title}</h2><p data-testid=\"job-sector\">{sector}</p><p data-testid=\"job-company\">{company}</p><p data-testid=\"job-location\">{anchor_city}, {state_code}</p><p data-testid=\"job-salary\">{salary_band}</p></article>"
        )

    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\" />"
        f"<title>{market_name} Jobs</title></head><body><main><section data-testid=\"job-results\">"
        + "".join(cards)
        + "</section></main></body></html>"
    )


FRISCO_PERMITS_HTML = _generate_permits_html("Frisco, TX", "TX", "Frisco")
FRISCO_MENU_HTML = _generate_menu_html("Frisco, TX", "TX")
FRISCO_JOBS_HTML = _generate_jobs_html("Frisco, TX", "TX", "Frisco")

DALLAS_PERMITS_HTML = _generate_permits_html("Dallas, TX", "TX", "Dallas")
DALLAS_MENU_HTML = _generate_menu_html("Dallas, TX", "TX")
DALLAS_JOBS_HTML = _generate_jobs_html("Dallas, TX", "TX", "Dallas")

AUSTIN_PERMITS_HTML = _generate_permits_html("Austin, TX", "TX", "Austin")
AUSTIN_MENU_HTML = _generate_menu_html("Austin, TX", "TX")
AUSTIN_JOBS_HTML = _generate_jobs_html("Austin, TX", "TX", "Austin")

CHICAGO_PERMITS_HTML = _generate_permits_html("Chicago, IL", "IL", "Chicago")
CHICAGO_MENU_HTML = _generate_menu_html("Chicago, IL", "IL")
CHICAGO_JOBS_HTML = _generate_jobs_html("Chicago, IL", "IL", "Chicago")


def _build_city_profile(
    slug: str,
    display_name: str,
    aliases: tuple[str, ...],
    state_code: str,
    permits_html: str,
    menu_html: str,
    jobs_html: str,
) -> LocationProfile:
    state_name = STATE_METADATA[state_code][0]
    return LocationProfile(
        slug=slug,
        display_name=display_name,
        aliases=aliases,
        permits_source_url=os.getenv(f"COMMERCIAL_PERMITS_URL_{slug.upper()}", f"mock://{slug}-commercial-permits"),
        menu_source_url=os.getenv(f"RESTAURANT_MENU_URL_{slug.upper()}", f"mock://{slug}-restaurant-menu"),
        jobs_source_url=os.getenv(f"LOCAL_JOBS_URL_{slug.upper()}", f"mock://{slug}-local-jobs"),
        permits_html=permits_html,
        menu_html=menu_html,
        jobs_html=jobs_html,
        source_market=display_name,
        state_code=state_code,
        state_name=state_name,
        coverage_mode="city",
    )


CITY_PROFILES: dict[str, LocationProfile] = {
    "frisco": _build_city_profile(
        "frisco",
        "Frisco, TX",
        ("frisco", "frisco tx", "frisco, tx"),
        "TX",
        FRISCO_PERMITS_HTML,
        FRISCO_MENU_HTML,
        FRISCO_JOBS_HTML,
    ),
    "dallas": _build_city_profile(
        "dallas",
        "Dallas, TX",
        ("dallas", "dallas tx", "dallas, tx"),
        "TX",
        DALLAS_PERMITS_HTML,
        DALLAS_MENU_HTML,
        DALLAS_JOBS_HTML,
    ),
    "austin": _build_city_profile(
        "austin",
        "Austin, TX",
        ("austin", "austin tx", "austin, tx"),
        "TX",
        AUSTIN_PERMITS_HTML,
        AUSTIN_MENU_HTML,
        AUSTIN_JOBS_HTML,
    ),
    "chicago": _build_city_profile(
        "chicago",
        "Chicago, IL",
        ("chicago", "chicago il", "chicago, il"),
        "IL",
        CHICAGO_PERMITS_HTML,
        CHICAGO_MENU_HTML,
        CHICAGO_JOBS_HTML,
    ),
}


def _build_state_profile(state_code: str) -> LocationProfile:
    state_name, anchor_city = STATE_METADATA[state_code]
    slug = _state_slug(state_code)
    return LocationProfile(
        slug=f"state-{slug}",
        display_name=state_name,
        aliases=_state_aliases(state_name, state_code),
        permits_source_url=os.getenv(f"COMMERCIAL_PERMITS_URL_STATE_{state_code}", f"mock://state-{slug}-commercial-permits"),
        menu_source_url=os.getenv(f"RESTAURANT_MENU_URL_STATE_{state_code}", f"mock://state-{slug}-restaurant-menu"),
        jobs_source_url=os.getenv(f"LOCAL_JOBS_URL_STATE_{state_code}", f"mock://state-{slug}-local-jobs"),
        permits_html=_generate_permits_html(f"{state_name} Statewide", state_code, anchor_city),
        menu_html=_generate_menu_html(f"{state_name} Statewide", state_code),
        jobs_html=_generate_jobs_html(f"{state_name} Statewide", state_code, anchor_city),
        source_market=f"{state_name} statewide",
        state_code=state_code,
        state_name=state_name,
        coverage_mode="state",
    )


STATE_PROFILES: dict[str, LocationProfile] = {
    code: _build_state_profile(code) for code in STATE_METADATA
}


def _build_state_fallback_profile(requested_city: str, state_code: str) -> LocationProfile:
    base = STATE_PROFILES[state_code]
    return LocationProfile(
        slug=f"{requested_city.lower().replace(' ', '-')}-{state_code.lower()}-fallback",
        display_name=f"{requested_city}, {state_code}",
        aliases=(f"{requested_city}, {state_code}", f"{requested_city} {state_code}"),
        permits_source_url=base.permits_source_url,
        menu_source_url=base.menu_source_url,
        jobs_source_url=base.jobs_source_url,
        permits_html=base.permits_html,
        menu_html=base.menu_html,
        jobs_html=base.jobs_html,
        source_market=base.source_market,
        state_code=state_code,
        state_name=base.state_name,
        coverage_mode="state_fallback",
    )


def resolve_location(query: str | None) -> LocationProfile:
    if not query:
        return CITY_PROFILES["frisco"]

    normalized = _normalize_city(query)
    for profile in CITY_PROFILES.values():
        alias_set = {_normalize_city(alias) for alias in profile.aliases}
        if normalized in alias_set:
            return profile

    for state_code, profile in STATE_PROFILES.items():
        alias_set = {_normalize_city(alias) for alias in profile.aliases}
        if normalized in alias_set:
            return profile

    state_candidates = []
    for state_code, (state_name, _) in STATE_METADATA.items():
        for alias in _state_aliases(state_name, state_code):
            normalized_alias = _normalize_city(alias)
            state_candidates.append((state_code, normalized_alias))

    state_candidates.sort(key=lambda item: len(item[1]), reverse=True)
    for state_code, alias in state_candidates:
        if normalized.endswith(f" {alias}"):
            requested_city = normalized[: -len(alias)].strip()
            if requested_city:
                return _build_state_fallback_profile(_titleize_location(requested_city), state_code)

    supported = ", ".join(supported_city_names())
    raise ValueError(
        "Unsupported location '"
        f"{query}" "'. Try a supported city, a state like California, or a city/state input like Phoenix, AZ. "
        f"Featured city support: {supported}."
    )


def resolve_city(query: str | None) -> LocationProfile:
    return resolve_location(query)


def supported_city_names() -> list[str]:
    return [profile.display_name for profile in CITY_PROFILES.values()]


def supported_state_names() -> list[str]:
    return [STATE_METADATA[code][0] for code in STATE_METADATA]


def suggested_location_names() -> list[str]:
    return supported_city_names() + supported_state_names()

"""Fetch benchmark prices and risk-free rates from public data sources.

S&P 500 (SPY): monthly closes from Stooq.com (no auth required).
Risk-free rate: 6-month T-bill yield from FRED (CSV endpoint, no API key).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date
from io import StringIO

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0


@dataclass
class PriceRow:
    date: date
    close_micros: int


@dataclass
class BenchmarkResult:
    prices: list[PriceRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def fetch_sp500_prices(start_year: int = 2015) -> BenchmarkResult:
    """Download monthly SPY closing prices from Stooq.

    Returns prices as micros (dollars * 1_000_000).
    """
    result = BenchmarkResult()
    d1 = f"{start_year}0101"
    d2 = date.today().strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s=spy.us&d1={d1}&d2={d2}&i=m"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            result.errors.append(f"Failed to fetch SPY data: {exc}")
            return result

    text = resp.text.strip()
    if not text or "No data" in text:
        result.errors.append("No SPY data returned from Stooq")
        return result

    reader = csv.DictReader(StringIO(text))
    for row_num, row in enumerate(reader, start=2):
        try:
            raw_date = row.get("Date", "")
            raw_close = row.get("Close", "")
            if not raw_date or not raw_close:
                continue
            price_date = date.fromisoformat(raw_date)
            close_micros = int(round(float(raw_close) * 1_000_000))
            result.prices.append(PriceRow(date=price_date, close_micros=close_micros))
        except (ValueError, KeyError) as exc:
            result.errors.append(f"Row {row_num}: {exc}")

    result.prices.sort(key=lambda p: p.date)
    return result


async def fetch_risk_free_rate_bps() -> tuple[int, str | None]:
    """Fetch the latest 6-month T-bill yield from FRED.

    Returns (rate_in_bps, error_message_or_none).
    100 bps = 1%.
    """
    cosd = (date.today().replace(day=1)).isoformat()
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS6MO&cosd={cosd}"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return 0, f"Failed to fetch T-bill rate: {exc}"

    text = resp.text.strip()
    if not text:
        return 0, "Empty response from FRED"

    latest_rate: float | None = None
    latest_date: str = ""
    reader = csv.DictReader(StringIO(text))
    for row in reader:
        val = row.get("DGS6MO", "").strip()
        if val and val != ".":
            try:
                latest_rate = float(val)
                latest_date = row.get("DATE", "")
            except ValueError:
                continue

    if latest_rate is None:
        return 0, "No valid T-bill rate found in FRED data"

    bps = int(round(latest_rate * 100))
    logger.info("FRED 6-month T-bill: %.2f%% (%d bps) as of %s", latest_rate, bps, latest_date)
    return bps, None

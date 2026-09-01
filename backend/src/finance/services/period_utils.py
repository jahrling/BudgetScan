import re
from datetime import date, timedelta

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_month_param(month: str) -> tuple[date, date]:
    """Parse a month string into (first_day, last_day) inclusive.

    Accepts "YYYY-MM" or "current".
    """
    if month == "current":
        today = date.today()
        year, mon = today.year, today.month
    elif _MONTH_RE.match(month):
        year, mon = int(month[:4]), int(month[5:7])
    else:
        raise ValueError(f"Invalid month format: {month!r}. Use 'YYYY-MM' or 'current'.")

    first = date(year, mon, 1)
    if mon == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, mon + 1, 1) - timedelta(days=1)

    return first, last


def month_str(d: date) -> str:
    """Return 'YYYY-MM' for a date."""
    return f"{d.year}-{d.month:02d}"


def prev_month_str(ym: str) -> str:
    """Return the YYYY-MM string for the month before *ym*."""
    year, mon = int(ym[:4]), int(ym[5:7])
    if mon == 1:
        return f"{year - 1}-12"
    return f"{year}-{mon - 1:02d}"

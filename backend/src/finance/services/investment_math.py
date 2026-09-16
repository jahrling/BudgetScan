"""Investment performance math — pure functions, no DB.

Modified Dietz sub-period returns, time-weighted return (TWR) via chain-linking,
money-weighted return (XIRR) via bracketed bisection + Newton polish, return
decomposition, and risk metrics (beta, alpha, R², Sharpe, volatility, max
drawdown).

All inputs use the same conventions as the rest of BudgetScan:
- Money as integer cents
- Quantities/prices as integer micros (× 1,000,000)

Design requirement (plan §3.3): everything in performance/risk must work from
monthly statement values plus known cash flows alone, with no external price
feed for the holdings.  Only the benchmark needs an external series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class CashFlow:
    """A dated cash flow for Modified Dietz or XIRR.

    For Modified Dietz: positive = money flowing IN (contribution),
    negative = money flowing OUT (withdrawal).

    For XIRR: follows the NPV sign convention — investments are negative,
    proceeds are positive.
    """
    date: date
    amount_cents: int


@dataclass
class Decomposition:
    """Return decomposition for a period: where did the change come from?"""
    net_contributions_cents: int
    income_cents: int
    price_appreciation_cents: int


@dataclass
class RiskMetrics:
    beta: float
    alpha_monthly: float
    alpha_annualized: float
    r_squared: float
    volatility_annualized: float
    sharpe_ratio: float
    max_drawdown: float
    n_months: int


# ---------------------------------------------------------------------------
# Modified Dietz sub-period return
# ---------------------------------------------------------------------------


def modified_dietz(
    bmv_cents: int,
    emv_cents: int,
    cash_flows: list[CashFlow],
    period_start: date,
    period_end: date,
) -> float:
    """Modified Dietz return for one sub-period.

    R = (EMV - BMV - CF) / (BMV + Σ wᵢ·CFᵢ)
    where wᵢ = (D - dᵢ) / D and D = total days in the period.

    Returns the decimal return (e.g., 0.05 for 5%).
    """
    total_days = (period_end - period_start).days
    if total_days <= 0:
        return 0.0

    total_cf = sum(cf.amount_cents for cf in cash_flows)
    weighted_cf = sum(
        cf.amount_cents * (total_days - (cf.date - period_start).days) / total_days
        for cf in cash_flows
    )

    denominator = bmv_cents + weighted_cf
    if denominator == 0:
        return 0.0

    return (emv_cents - bmv_cents - total_cf) / denominator


# ---------------------------------------------------------------------------
# Time-weighted return (TWR) — chain-link sub-period returns
# ---------------------------------------------------------------------------


def twr(sub_period_returns: list[float]) -> float:
    """Time-weighted return: Π(1 + Rₜ) - 1."""
    product = 1.0
    for r in sub_period_returns:
        product *= (1.0 + r)
    return product - 1.0


def monthly_return_series(
    snapshots: list[tuple[date, int]],
    cash_flows: list[CashFlow],
) -> list[tuple[date, float]]:
    """Produce a monthly return series from dated valuation snapshots.

    ``snapshots`` is a sorted list of (date, market_value_cents).
    ``cash_flows`` are all flows in the period, sorted by date.

    Returns (month_end_date, modified_dietz_return) for each adjacent pair.
    """
    if len(snapshots) < 2:
        return []

    result: list[tuple[date, float]] = []
    for i in range(1, len(snapshots)):
        start_date, bmv = snapshots[i - 1]
        end_date, emv = snapshots[i]
        period_flows = [
            cf for cf in cash_flows
            if start_date < cf.date <= end_date
        ]
        r = modified_dietz(bmv, emv, period_flows, start_date, end_date)
        result.append((end_date, r))

    return result


# ---------------------------------------------------------------------------
# Money-weighted return (XIRR)
# ---------------------------------------------------------------------------


def xirr(cash_flows: list[CashFlow], guess: float = 0.1, max_iter: int = 200) -> float | None:
    """Solve for the annualized IRR of irregularly spaced cash flows.

    Σ CFᵢ / (1+r)^(tᵢ/365) = 0

    Uses bracketed bisection to find sign change, then Newton-Raphson polish.
    Returns the annual rate as a decimal (e.g., 0.3734 for 37.34%), or None
    if no solution is found.
    """
    if not cash_flows:
        return None

    dates = [cf.date for cf in cash_flows]
    base_date = min(dates)
    amounts = [cf.amount_cents for cf in cash_flows]
    day_fracs = [(d - base_date).days / 365.0 for d in dates]

    def npv(rate: float) -> float:
        return sum(
            a / (1.0 + rate) ** t
            for a, t in zip(amounts, day_fracs)
        )

    def npv_deriv(rate: float) -> float:
        return sum(
            -t * a / (1.0 + rate) ** (t + 1.0)
            for a, t in zip(amounts, day_fracs)
        )

    # Phase 1: bracket — find an interval [lo, hi] where NPV changes sign.
    lo, hi = -0.99, 10.0
    npv_lo = npv(lo)

    # If NPV at both extremes has the same sign, widen the search.
    if npv_lo * npv(hi) > 0:
        for candidate in [20.0, 50.0, 100.0]:
            if npv_lo * npv(candidate) <= 0:
                hi = candidate
                break
        else:
            return None

    # Bisection to narrow the bracket.
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
        if abs(hi - lo) < 1e-10:
            break

    # Phase 2: Newton-Raphson polish from the bisection midpoint.
    rate = (lo + hi) / 2.0
    for _ in range(max_iter):
        f = npv(rate)
        fp = npv_deriv(rate)
        if abs(fp) < 1e-14:
            break
        step = f / fp
        rate -= step
        if abs(step) < 1e-10:
            break
        # Stay in bracket
        if rate <= -1.0:
            rate = -0.99

    if abs(npv(rate)) > 0.01:
        return None

    return rate


# ---------------------------------------------------------------------------
# Return decomposition
# ---------------------------------------------------------------------------


def decompose_return(
    beginning_value_cents: int,
    ending_value_cents: int,
    net_contributions_cents: int,
    income_cents: int,
) -> Decomposition:
    """Break the period's value change into components.

    ending - beginning = contributions + income + price_appreciation
    """
    total_change = ending_value_cents - beginning_value_cents
    price_appreciation = total_change - net_contributions_cents - income_cents
    return Decomposition(
        net_contributions_cents=net_contributions_cents,
        income_cents=income_cents,
        price_appreciation_cents=price_appreciation,
    )


# ---------------------------------------------------------------------------
# Risk metrics (monthly excess returns)
# ---------------------------------------------------------------------------


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _cov(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)


def _var(xs: list[float]) -> float:
    return _cov(xs, xs)


def compute_risk_metrics(
    portfolio_returns: list[float],
    benchmark_returns: list[float],
    risk_free_annual: float = 0.0,
) -> RiskMetrics | None:
    """Compute beta, alpha, and related risk metrics from monthly return series.

    Both series must be the same length and represent the same months.
    ``risk_free_annual`` is the annual rate (e.g., 0.05 for 5%).

    Returns None if n < 12 (too few data points to be meaningful).
    """
    n = len(portfolio_returns)
    if n != len(benchmark_returns) or n < 12:
        return None

    rf_monthly = (1.0 + risk_free_annual) ** (1.0 / 12.0) - 1.0

    excess_p = [r - rf_monthly for r in portfolio_returns]
    excess_m = [r - rf_monthly for r in benchmark_returns]

    var_m = _var(excess_m)
    if var_m == 0:
        return None

    beta = _cov(excess_p, excess_m) / var_m
    alpha_monthly = _mean(excess_p) - beta * _mean(excess_m)
    alpha_annualized = (1.0 + alpha_monthly) ** 12 - 1.0

    # R² = correlation² = Cov²/(Var_p · Var_m)
    var_p = _var(excess_p)
    if var_p == 0:
        r_squared = 0.0
    else:
        cov_pm = _cov(excess_p, excess_m)
        r_squared = (cov_pm ** 2) / (var_p * var_m)

    # Annualized volatility
    std_p = math.sqrt(var_p) if var_p > 0 else 0.0
    volatility_annualized = std_p * math.sqrt(12)

    # Sharpe ratio
    mean_excess = _mean(excess_p)
    sharpe_ratio = (mean_excess / std_p * math.sqrt(12)) if std_p > 0 else 0.0

    # Max drawdown from cumulative TWR series
    max_drawdown = _max_drawdown(portfolio_returns)

    return RiskMetrics(
        beta=beta,
        alpha_monthly=alpha_monthly,
        alpha_annualized=alpha_annualized,
        r_squared=r_squared,
        volatility_annualized=volatility_annualized,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        n_months=n,
    )


def _max_drawdown(returns: list[float]) -> float:
    """Maximum peak-to-trough decline in the cumulative return series."""
    if not returns:
        return 0.0

    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0

    for r in returns:
        cumulative *= (1.0 + r)
        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak
        if dd > max_dd:
            max_dd = dd

    return max_dd

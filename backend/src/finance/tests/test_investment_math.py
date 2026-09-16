"""Investment math: Modified Dietz, TWR, XIRR, return decomposition, risk metrics."""

from datetime import date

import pytest

from finance.services.investment_math import (
    CashFlow,
    compute_risk_metrics,
    decompose_return,
    modified_dietz,
    monthly_return_series,
    twr,
    xirr,
)


# ---------------------------------------------------------------------------
# Modified Dietz
# ---------------------------------------------------------------------------


class TestModifiedDietz:
    def test_no_cash_flows(self):
        # $100,000 → $105,000 over 30 days, no flows
        r = modified_dietz(
            10_000_000, 10_500_000, [],
            date(2024, 6, 1), date(2024, 7, 1),
        )
        assert r == pytest.approx(0.05, abs=1e-9)

    def test_with_contribution_midperiod(self):
        # BMV = $100,000, EMV = $112,000, contribution of $10,000 on day 15 of 30
        # CF = +10,000 → total_cf = $10,000
        # Gain net of flows = $112,000 - $100,000 - $10,000 = $2,000
        # Weight = (30 - 15) / 30 = 0.5
        # Denominator = $100,000 + 0.5 * $10,000 = $105,000
        # R = $2,000 / $105,000 ≈ 0.019048
        r = modified_dietz(
            10_000_000, 11_200_000,
            [CashFlow(date(2024, 6, 16), 1_000_000)],
            date(2024, 6, 1), date(2024, 7, 1),
        )
        assert r == pytest.approx(2_000_00 / 10_500_000, abs=1e-6)

    def test_withdrawal(self):
        # BMV = $200,000, EMV = $180,000, withdrawal of $25,000 on day 10 of 30
        # Gain = $180,000 - $200,000 - (-$25,000) = $5,000
        # Weight = (30 - 10) / 30 = 2/3
        # Denom = $200,000 + (2/3)(-$25,000) = $183,333.33
        # R = $5,000 / $183,333.33 ≈ 0.02727
        r = modified_dietz(
            20_000_000, 18_000_000,
            [CashFlow(date(2024, 6, 11), -2_500_000)],
            date(2024, 6, 1), date(2024, 7, 1),
        )
        assert r == pytest.approx(500_000 / (20_000_000 + (-2_500_000) * 20 / 30), abs=1e-6)

    def test_zero_period(self):
        r = modified_dietz(
            10_000_000, 10_000_000, [],
            date(2024, 6, 1), date(2024, 6, 1),
        )
        assert r == 0.0

    def test_multiple_flows(self):
        # BMV=$50k, EMV=$60k, two flows: +$3k on day 5, -$2k on day 20 (of 30)
        # net CF = $1k
        # Gain = $60k - $50k - $1k = $9k
        # Weighted CF = $3k * (30-5)/30 + (-$2k) * (30-20)/30
        #             = $3k * 25/30 + (-$2k) * 10/30
        #             = $2500 - $666.67 = $1833.33
        # Denom = $50k + $1833.33 = $51833.33
        r = modified_dietz(
            5_000_000, 6_000_000,
            [
                CashFlow(date(2024, 6, 6), 300_000),
                CashFlow(date(2024, 6, 21), -200_000),
            ],
            date(2024, 6, 1), date(2024, 7, 1),
        )
        weighted_cf = 300_000 * 25 / 30 + (-200_000) * 10 / 30
        expected = 900_000 / (5_000_000 + weighted_cf)
        assert r == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# TWR chain-linking
# ---------------------------------------------------------------------------


class TestTWR:
    def test_chain_link_two_periods(self):
        # 5% then 3% → (1.05)(1.03) - 1 = 0.0815
        assert twr([0.05, 0.03]) == pytest.approx(0.0815, abs=1e-9)

    def test_empty(self):
        assert twr([]) == pytest.approx(0.0, abs=1e-9)

    def test_single_period(self):
        assert twr([0.12]) == pytest.approx(0.12, abs=1e-9)

    def test_loss_and_gain(self):
        # -10% then +20% → (0.9)(1.2) - 1 = 0.08
        assert twr([-0.10, 0.20]) == pytest.approx(0.08, abs=1e-9)

    def test_twelve_months_constant(self):
        # 1% per month for 12 months → (1.01)^12 - 1
        expected = 1.01**12 - 1
        assert twr([0.01] * 12) == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# Monthly return series
# ---------------------------------------------------------------------------


class TestMonthlyReturnSeries:
    def test_three_months(self):
        snapshots = [
            (date(2024, 3, 31), 10_000_000),
            (date(2024, 4, 30), 10_300_000),
            (date(2024, 5, 31), 10_600_000),
        ]
        series = monthly_return_series(snapshots, [])
        assert len(series) == 2
        assert series[0][0] == date(2024, 4, 30)
        assert series[0][1] == pytest.approx(0.03, abs=1e-6)
        assert series[1][0] == date(2024, 5, 31)
        # 10_600_000 / 10_300_000 - 1 ≈ 0.02913
        assert series[1][1] == pytest.approx(300_000 / 10_300_000, abs=1e-6)

    def test_with_cash_flow_in_period(self):
        snapshots = [
            (date(2024, 3, 31), 10_000_000),
            (date(2024, 4, 30), 11_200_000),
        ]
        flows = [CashFlow(date(2024, 4, 15), 1_000_000)]
        series = monthly_return_series(snapshots, flows)
        assert len(series) == 1
        expected = modified_dietz(
            10_000_000, 11_200_000, flows,
            date(2024, 3, 31), date(2024, 4, 30),
        )
        assert series[0][1] == pytest.approx(expected, abs=1e-9)

    def test_fewer_than_two_snapshots(self):
        assert monthly_return_series([(date(2024, 1, 31), 100)], []) == []
        assert monthly_return_series([], []) == []


# ---------------------------------------------------------------------------
# XIRR — Excel standard fixture from plan §3.3
# ---------------------------------------------------------------------------


class TestXIRR:
    def test_excel_standard_example(self):
        """The plan specifies this exact fixture:
        -10000 on 2008-01-01, 2750 on 2008-03-01, 4250 on 2008-10-30,
        3250 on 2009-02-15, 2750 on 2009-04-01 → 37.34%.
        """
        flows = [
            CashFlow(date(2008, 1, 1), -10000_00),
            CashFlow(date(2008, 3, 1), 2750_00),
            CashFlow(date(2008, 10, 30), 4250_00),
            CashFlow(date(2009, 2, 15), 3250_00),
            CashFlow(date(2009, 4, 1), 2750_00),
        ]
        rate = xirr(flows)
        assert rate is not None
        assert rate == pytest.approx(0.3734, abs=0.001)

    def test_simple_doubling_in_one_year(self):
        # Invest $1000, get back $2000 exactly one year later → 100%
        flows = [
            CashFlow(date(2024, 1, 1), -100_000),
            CashFlow(date(2025, 1, 1), 200_000),
        ]
        rate = xirr(flows)
        assert rate is not None
        assert rate == pytest.approx(1.0, abs=0.005)  # 366-day year shifts slightly

    def test_break_even(self):
        # Invest $1000, get back $1000 a year later → 0%
        flows = [
            CashFlow(date(2024, 1, 1), -100_000),
            CashFlow(date(2025, 1, 1), 100_000),
        ]
        rate = xirr(flows)
        assert rate is not None
        assert rate == pytest.approx(0.0, abs=0.001)

    def test_loss(self):
        # Invest $1000, get back $500 → negative return
        flows = [
            CashFlow(date(2024, 1, 1), -100_000),
            CashFlow(date(2025, 1, 1), 50_000),
        ]
        rate = xirr(flows)
        assert rate is not None
        assert rate < 0

    def test_empty_returns_none(self):
        assert xirr([]) is None

    def test_portfolio_xirr_with_bmv_emv(self):
        """XIRR for a portfolio: BMV as outflow, EMV as inflow, with
        intermediate contributions and withdrawals."""
        # Start with $100k, contribute $20k after 3 months, end at $135k after 1 year
        flows = [
            CashFlow(date(2024, 1, 1), -10_000_000),    # BMV
            CashFlow(date(2024, 4, 1), -2_000_000),      # contribution
            CashFlow(date(2025, 1, 1), 13_500_000),      # EMV
        ]
        rate = xirr(flows)
        assert rate is not None
        # Invested $120k, ended at $135k. With timing, ~12-13%.
        assert 0.05 < rate < 0.20


# ---------------------------------------------------------------------------
# Return decomposition
# ---------------------------------------------------------------------------


class TestDecomposition:
    def test_all_components(self):
        # Start $100k, end $130k, contributed $10k, received $5k income
        # Price appreciation = $130k - $100k - $10k - $5k = $15k
        d = decompose_return(10_000_000, 13_000_000, 1_000_000, 500_000)
        assert d.net_contributions_cents == 1_000_000
        assert d.income_cents == 500_000
        assert d.price_appreciation_cents == 1_500_000

    def test_loss_period(self):
        # Start $100k, end $85k, withdrew $5k, $2k income
        # Price appreciation = $85k - $100k - (-$5k) - $2k = -$12k
        d = decompose_return(10_000_000, 8_500_000, -500_000, 200_000)
        assert d.price_appreciation_cents == -1_200_000

    def test_zero_change(self):
        d = decompose_return(10_000_000, 10_000_000, 0, 0)
        assert d.price_appreciation_cents == 0


# ---------------------------------------------------------------------------
# Risk metrics — β/α identity fixture from plan §3.4
# ---------------------------------------------------------------------------


class TestRiskMetrics:
    def test_identity_fixture(self):
        """Plan §3.4: series with Rᵢ = 0.5·Rₘ + 0.01 must return
        β=0.5, α_monthly=0.01, R²=1.
        """
        # 24 months of benchmark returns (arbitrary but varied)
        benchmark = [
            0.02, -0.01, 0.03, 0.015, -0.005, 0.025,
            0.01, -0.02, 0.035, 0.005, -0.015, 0.04,
            0.02, -0.01, 0.03, 0.015, -0.005, 0.025,
            0.01, -0.02, 0.035, 0.005, -0.015, 0.04,
        ]
        # Portfolio = 0.5 * benchmark + 0.01
        portfolio = [0.5 * rm + 0.01 for rm in benchmark]

        metrics = compute_risk_metrics(portfolio, benchmark, risk_free_annual=0.0)
        assert metrics is not None
        assert metrics.beta == pytest.approx(0.5, abs=1e-6)
        assert metrics.alpha_monthly == pytest.approx(0.01, abs=1e-6)
        assert metrics.r_squared == pytest.approx(1.0, abs=1e-6)
        assert metrics.n_months == 24

    def test_perfect_correlation_beta_one(self):
        # Portfolio tracks benchmark exactly → β=1, α=0, R²=1
        benchmark = [0.02, -0.01, 0.03, 0.015, -0.005, 0.025,
                     0.01, -0.02, 0.035, 0.005, -0.015, 0.04]
        metrics = compute_risk_metrics(benchmark, benchmark, risk_free_annual=0.0)
        assert metrics is not None
        assert metrics.beta == pytest.approx(1.0, abs=1e-6)
        assert metrics.alpha_monthly == pytest.approx(0.0, abs=1e-6)
        assert metrics.r_squared == pytest.approx(1.0, abs=1e-6)

    def test_refuses_under_12_months(self):
        benchmark = [0.01] * 11
        portfolio = [0.01] * 11
        assert compute_risk_metrics(portfolio, benchmark) is None

    def test_length_mismatch_returns_none(self):
        assert compute_risk_metrics([0.01] * 12, [0.01] * 13) is None

    def test_alpha_annualized(self):
        # With α_monthly = 0.01, annualized = (1.01)^12 - 1 ≈ 0.1268
        benchmark = [0.02, -0.01, 0.03, 0.015, -0.005, 0.025,
                     0.01, -0.02, 0.035, 0.005, -0.015, 0.04] * 2
        portfolio = [0.5 * rm + 0.01 for rm in benchmark]
        metrics = compute_risk_metrics(portfolio, benchmark)
        assert metrics is not None
        expected_annual = (1.01) ** 12 - 1
        assert metrics.alpha_annualized == pytest.approx(expected_annual, abs=1e-4)

    def test_with_risk_free_rate(self):
        # β/α with rf = 5% annual
        benchmark = [0.02, -0.01, 0.03, 0.015, -0.005, 0.025,
                     0.01, -0.02, 0.035, 0.005, -0.015, 0.04] * 2
        portfolio = [0.5 * rm + 0.01 for rm in benchmark]
        metrics = compute_risk_metrics(portfolio, benchmark, risk_free_annual=0.05)
        assert metrics is not None
        # β should still be 0.5 (rf shifts both series equally)
        assert metrics.beta == pytest.approx(0.5, abs=1e-4)

    def test_volatility_positive_for_varying_returns(self):
        benchmark = [0.02, -0.01, 0.03, 0.015, -0.005, 0.025,
                     0.01, -0.02, 0.035, 0.005, -0.015, 0.04]
        metrics = compute_risk_metrics(benchmark, benchmark)
        assert metrics is not None
        assert metrics.volatility_annualized > 0

    def test_sharpe_ratio(self):
        # Constant positive excess returns → high Sharpe
        benchmark = [0.0] * 12
        portfolio = [0.01] * 12  # 1% every month, no variance
        # With zero benchmark variance, compute_risk_metrics returns None
        # because var_m == 0. Use a tiny varying benchmark instead.
        benchmark = [0.001 * (i % 3 - 1) for i in range(12)]
        portfolio = [0.01] * 12
        metrics = compute_risk_metrics(portfolio, benchmark)
        assert metrics is not None
        # Sharpe should be high (consistent excess returns, zero portfolio variance)
        # Actually portfolio has zero variance too, so Sharpe = 0 (0/0 case)
        # Let's add a bit of variance
        portfolio = [0.01 + 0.001 * (i % 2) for i in range(12)]
        metrics = compute_risk_metrics(portfolio, benchmark)
        assert metrics is not None
        assert metrics.sharpe_ratio > 0


class TestMaxDrawdown:
    def test_no_drawdown(self):
        # Monotonically increasing → no drawdown
        portfolio = [0.01] * 12
        benchmark = [0.001 * (i % 5 - 2) for i in range(12)]
        metrics = compute_risk_metrics(portfolio, benchmark)
        assert metrics is not None
        assert metrics.max_drawdown == pytest.approx(0.0, abs=1e-9)

    def test_known_drawdown(self):
        # Up 10%, then down 20%, then up 15%
        # Peak at 1.1, trough at 1.1 * 0.8 = 0.88, DD = (1.1-0.88)/1.1 = 0.2
        # Need 12+ months with non-zero benchmark variance.
        returns = [0.10, -0.20, 0.15] + [0.0] * 9
        benchmark = [0.01 * (1 + i % 3) for i in range(12)]
        metrics = compute_risk_metrics(returns, benchmark)
        assert metrics is not None
        assert metrics.max_drawdown == pytest.approx(0.20, abs=0.01)

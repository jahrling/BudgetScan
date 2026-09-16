"""Lot engine: FIFO lot tracking, splits, return of capital, reinvestment."""

from datetime import date

from finance.services.lot_engine import (
    TxnInput,
    rebuild_lots,
)


def _buy(id: int, d: date, qty: int, amount: int, fee: int = 0) -> TxnInput:
    return TxnInput(
        id=id, action="buy", trade_date=d,
        quantity_micros=qty, amount_cents=-amount, fee_cents=fee,
    )


def _reinvest_div(id: int, d: date, qty: int, amount: int) -> TxnInput:
    return TxnInput(
        id=id, action="reinvest_dividend", trade_date=d,
        quantity_micros=qty, amount_cents=amount,
    )


def _sell(id: int, d: date, qty: int, amount: int, fee: int = 0) -> TxnInput:
    return TxnInput(
        id=id, action="sell", trade_date=d,
        quantity_micros=qty, amount_cents=amount, fee_cents=fee,
    )


def _dividend(id: int, d: date, amount: int) -> TxnInput:
    return TxnInput(
        id=id, action="dividend", trade_date=d,
        amount_cents=amount,
    )


def _split(id: int, d: date, post_split_qty: int) -> TxnInput:
    return TxnInput(
        id=id, action="split", trade_date=d,
        quantity_micros=post_split_qty,
    )


def _return_of_capital(id: int, d: date, amount: int) -> TxnInput:
    return TxnInput(
        id=id, action="return_of_capital", trade_date=d,
        amount_cents=amount,
    )


def _shares_in(id: int, d: date, qty: int) -> TxnInput:
    return TxnInput(
        id=id, action="shares_in", trade_date=d,
        quantity_micros=qty, amount_cents=0,
    )


# ---------------------------------------------------------------------------
# Basic buy
# ---------------------------------------------------------------------------


class TestSingleBuy:
    def test_one_lot_created(self):
        # Buy 100 shares at $50 = $5000
        result = rebuild_lots([_buy(1, date(2024, 1, 15), 100_000_000, 500_000)])
        assert len(result.lots) == 1
        lot = result.lots[0]
        assert lot.quantity_micros_original == 100_000_000
        assert lot.quantity_micros_remaining == 100_000_000
        assert lot.cost_basis_cents == 500_000
        assert lot.is_reinvestment is False
        assert lot.opened_at == date(2024, 1, 15)
        assert lot.opened_by_txn_id == 1

    def test_aggregates(self):
        result = rebuild_lots([_buy(1, date(2024, 1, 15), 100_000_000, 500_000)])
        assert result.cost_basis_cents == 500_000
        assert result.invested_capital_cents == 500_000
        assert result.realized_gain_cents == 0
        assert result.income_received_cents == 0

    def test_fee_added_to_basis(self):
        # Buy $5000 + $10 fee
        result = rebuild_lots([
            _buy(1, date(2024, 1, 15), 100_000_000, 500_000, fee=1000),
        ])
        assert result.lots[0].cost_basis_cents == 501_000
        assert result.cost_basis_cents == 501_000


# ---------------------------------------------------------------------------
# FIFO sell order
# ---------------------------------------------------------------------------


class TestFIFOSell:
    def test_sells_oldest_first(self):
        # Buy 50 shares on Jan 1 at $40 = $2000
        # Buy 50 shares on Feb 1 at $60 = $3000
        # Sell 50 shares on Jul 1 at $55 = $2750
        # FIFO: closes the Jan lot (basis $2000), gain = $750
        txns = [
            _buy(1, date(2024, 1, 1), 50_000_000, 200_000),
            _buy(2, date(2024, 2, 1), 50_000_000, 300_000),
            _sell(3, date(2024, 7, 1), 50_000_000, 275_000),
        ]
        result = rebuild_lots(txns)

        assert len(result.disposals) == 1
        d = result.disposals[0]
        assert d.lot_index == 0  # oldest lot
        assert d.quantity_micros == 50_000_000
        assert d.proceeds_cents == 275_000
        assert d.basis_cents == 200_000
        assert d.realized_gain_cents == 75_000
        assert d.term == "short"  # Jan 1 → Jul 1 = 182 days < 365

    def test_short_term_under_365_days(self):
        txns = [
            _buy(1, date(2024, 1, 1), 50_000_000, 200_000),
            _sell(2, date(2024, 7, 1), 50_000_000, 275_000),
        ]
        result = rebuild_lots(txns)
        assert result.disposals[0].term == "short"  # 182 days

    def test_long_term_over_365_days(self):
        txns = [
            _buy(1, date(2024, 1, 1), 50_000_000, 200_000),
            _sell(2, date(2025, 1, 2), 50_000_000, 275_000),  # 367 days
        ]
        result = rebuild_lots(txns)
        assert result.disposals[0].term == "long"

    def test_partial_sell_from_first_lot(self):
        # Buy 100 shares at $50 = $5000
        # Sell 30 shares at $60 = $1800
        # Basis for 30 of 100 shares = $5000 * 30/100 = $1500
        # Gain = $1800 - $1500 = $300
        txns = [
            _buy(1, date(2024, 1, 1), 100_000_000, 500_000),
            _sell(2, date(2024, 3, 1), 30_000_000, 180_000),
        ]
        result = rebuild_lots(txns)

        assert len(result.disposals) == 1
        d = result.disposals[0]
        assert d.quantity_micros == 30_000_000
        assert d.basis_cents == 150_000  # 30/100 of $5000
        assert d.proceeds_cents == 180_000
        assert d.realized_gain_cents == 30_000

        # Remaining lot
        lot = result.lots[0]
        assert lot.quantity_micros_remaining == 70_000_000
        assert lot.cost_basis_cents == 350_000  # 70/100 of $5000

    def test_sell_spans_two_lots(self):
        # Lot 1: 30 shares at $40 = $1200
        # Lot 2: 70 shares at $50 = $3500
        # Sell 50 shares at $55 = $2750
        # FIFO: 30 from lot 1 (basis $1200), 20 from lot 2 (basis $3500 * 20/70 = $1000)
        txns = [
            _buy(1, date(2024, 1, 1), 30_000_000, 120_000),
            _buy(2, date(2024, 2, 1), 70_000_000, 350_000),
            _sell(3, date(2024, 4, 1), 50_000_000, 275_000),
        ]
        result = rebuild_lots(txns)

        assert len(result.disposals) == 2
        # First disposal: all 30 from lot 1
        d0 = result.disposals[0]
        assert d0.lot_index == 0
        assert d0.quantity_micros == 30_000_000
        assert d0.basis_cents == 120_000
        # Proceeds: 30/50 of $2750 = $1650
        assert d0.proceeds_cents == 165_000

        # Second disposal: 20 from lot 2
        d1 = result.disposals[1]
        assert d1.lot_index == 1
        assert d1.quantity_micros == 20_000_000
        assert d1.basis_cents == 100_000  # 20/70 of $3500
        # Proceeds: 20/50 of $2750 = $1100
        assert d1.proceeds_cents == 110_000

        # Total realized gain
        total_gain = d0.realized_gain_cents + d1.realized_gain_cents
        assert total_gain == result.realized_gain_cents
        # ($1650 - $1200) + ($1100 - $1000) = $450 + $100 = $550
        assert total_gain == 55_000

    def test_proceeds_sum_exact_across_lots(self):
        # Sell 3 shares for $100.00 across 3 single-share lots.
        # Without remainder allocation: 3 * round(3333.33) = 9999, not 10000.
        txns = [
            _buy(1, date(2024, 1, 1), 1_000_000, 3_000),
            _buy(2, date(2024, 1, 2), 1_000_000, 3_000),
            _buy(3, date(2024, 1, 3), 1_000_000, 3_000),
            _sell(4, date(2024, 3, 1), 3_000_000, 10_000),
        ]
        result = rebuild_lots(txns)
        total_proceeds = sum(d.proceeds_cents for d in result.disposals)
        assert total_proceeds == 10_000

    def test_sell_with_fee_reduces_proceeds(self):
        txns = [
            _buy(1, date(2024, 1, 1), 100_000_000, 500_000),
            _sell(2, date(2024, 3, 1), 100_000_000, 600_000, fee=500),
        ]
        result = rebuild_lots(txns)
        d = result.disposals[0]
        # Proceeds = $6000 - $5 fee = $5995
        assert d.proceeds_cents == 599_500
        assert d.realized_gain_cents == 99_500  # $5995 - $5000


# ---------------------------------------------------------------------------
# Reinvestment tracking
# ---------------------------------------------------------------------------


class TestReinvestment:
    def test_reinvest_dividend_creates_lot(self):
        # Buy 100 shares at $50
        # Receive $200 dividend, reinvest at $52 = 3.846154 shares
        txns = [
            _buy(1, date(2024, 1, 1), 100_000_000, 500_000),
            _reinvest_div(2, date(2024, 4, 1), 3_846_154, 20_000),
        ]
        result = rebuild_lots(txns)

        assert len(result.lots) == 2
        reinv_lot = result.lots[1]
        assert reinv_lot.is_reinvestment is True
        assert reinv_lot.quantity_micros_original == 3_846_154
        assert reinv_lot.cost_basis_cents == 20_000

    def test_invested_capital_excludes_reinvestment(self):
        txns = [
            _buy(1, date(2024, 1, 1), 100_000_000, 500_000),
            _reinvest_div(2, date(2024, 4, 1), 3_846_154, 20_000),
        ]
        result = rebuild_lots(txns)

        # Cost basis includes everything
        assert result.cost_basis_cents == 520_000  # $5000 + $200
        # Invested capital excludes reinvested income
        assert result.invested_capital_cents == 500_000  # only the $5000 buy

    def test_income_received_counts_reinvested(self):
        txns = [
            _buy(1, date(2024, 1, 1), 100_000_000, 500_000),
            _reinvest_div(2, date(2024, 4, 1), 3_846_154, 20_000),
            _dividend(3, date(2024, 7, 1), 15_000),
        ]
        result = rebuild_lots(txns)
        # Both the reinvested dividend ($200) and cash dividend ($150) count
        assert result.income_received_cents == 35_000


# ---------------------------------------------------------------------------
# Stock split
# ---------------------------------------------------------------------------


class TestStockSplit:
    def test_2_for_1_split(self):
        # Buy 100 shares at $80 = $8000
        # 2:1 split → 200 shares, basis unchanged
        txns = [
            _buy(1, date(2024, 1, 1), 100_000_000, 800_000),
            _split(2, date(2024, 6, 1), 200_000_000),
        ]
        result = rebuild_lots(txns)

        lot = result.lots[0]
        assert lot.quantity_micros_original == 200_000_000
        assert lot.quantity_micros_remaining == 200_000_000
        assert lot.cost_basis_cents == 800_000  # unchanged

    def test_split_across_multiple_lots(self):
        # Lot 1: 60 shares, Lot 2: 40 shares, total 100
        # 3:1 split → 300 shares total
        txns = [
            _buy(1, date(2024, 1, 1), 60_000_000, 300_000),
            _buy(2, date(2024, 2, 1), 40_000_000, 200_000),
            _split(3, date(2024, 6, 1), 300_000_000),
        ]
        result = rebuild_lots(txns)

        # Each lot scaled by 3x
        assert result.lots[0].quantity_micros_remaining == 180_000_000
        assert result.lots[1].quantity_micros_remaining == 120_000_000
        # Basis unchanged
        assert result.lots[0].cost_basis_cents == 300_000
        assert result.lots[1].cost_basis_cents == 200_000


# ---------------------------------------------------------------------------
# Return of capital
# ---------------------------------------------------------------------------


class TestReturnOfCapital:
    def test_reduces_basis_pro_rata(self):
        # Lot 1: basis $3000, Lot 2: basis $7000, total $10000
        # Return of capital $500 → lot 1 gets $150, lot 2 gets $350
        txns = [
            _buy(1, date(2024, 1, 1), 30_000_000, 300_000),
            _buy(2, date(2024, 2, 1), 70_000_000, 700_000),
            _return_of_capital(3, date(2024, 6, 1), 50_000),
        ]
        result = rebuild_lots(txns)

        assert result.lots[0].cost_basis_cents == 285_000  # $3000 - $150
        assert result.lots[1].cost_basis_cents == 665_000  # $7000 - $350
        assert result.cost_basis_cents == 950_000

    def test_basis_cannot_go_negative(self):
        # Small lot with $100 basis, $200 return of capital
        txns = [
            _buy(1, date(2024, 1, 1), 10_000_000, 10_000),
            _return_of_capital(2, date(2024, 6, 1), 20_000),
        ]
        result = rebuild_lots(txns)
        assert result.lots[0].cost_basis_cents == 0  # clamped, not negative


# ---------------------------------------------------------------------------
# Shares in (transferred-in positions)
# ---------------------------------------------------------------------------


class TestSharesIn:
    def test_shares_in_creates_lot_with_zero_basis(self):
        txns = [_shares_in(1, date(2024, 1, 1), 500_000_000)]
        result = rebuild_lots(txns)
        assert len(result.lots) == 1
        lot = result.lots[0]
        assert lot.quantity_micros_original == 500_000_000
        assert lot.cost_basis_cents == 0
        assert lot.is_reinvestment is False


# ---------------------------------------------------------------------------
# Complex scenario: buy, reinvest, sell, dividend sequence
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    def test_lifecycle(self):
        # 1. Buy 100 shares at $50 = $5000
        # 2. Dividend $300 (cash)
        # 3. Reinvest dividend: 5 shares at $52 = $260
        # 4. Sell 60 shares at $55 = $3300 (FIFO from lot 1)
        #    basis = $5000 * 60/100 = $3000, gain = $300
        # 5. Another dividend $200 (cash)
        txns = [
            _buy(1, date(2024, 1, 1), 100_000_000, 500_000),
            _dividend(2, date(2024, 3, 1), 30_000),
            _reinvest_div(3, date(2024, 4, 1), 5_000_000, 26_000),
            _sell(4, date(2024, 8, 1), 60_000_000, 330_000),
            _dividend(5, date(2024, 10, 1), 20_000),
        ]
        result = rebuild_lots(txns)

        # Open lots: 40 shares from lot 1 + 5 shares from reinvest lot
        open_lots = [lot for lot in result.lots if lot.quantity_micros_remaining > 0]
        assert len(open_lots) == 2
        assert open_lots[0].quantity_micros_remaining == 40_000_000  # 100-60
        assert open_lots[1].quantity_micros_remaining == 5_000_000   # reinvest

        # Cost basis: lot 1 remaining ($5000 * 40/100 = $2000) + reinvest ($260)
        assert result.cost_basis_cents == 200_000 + 26_000  # $2260

        # Invested capital: only the original buy's remaining portion
        assert result.invested_capital_cents == 200_000  # $2000

        # Realized gain: sold 60 shares, proceeds $3300, basis $3000
        assert result.realized_gain_cents == 30_000

        # Income: $300 + $260 (reinvested) + $200 = $760
        assert result.income_received_cents == 76_000

    def test_empty_input(self):
        result = rebuild_lots([])
        assert result.lots == []
        assert result.disposals == []
        assert result.cost_basis_cents == 0
        assert result.invested_capital_cents == 0
        assert result.realized_gain_cents == 0
        assert result.income_received_cents == 0

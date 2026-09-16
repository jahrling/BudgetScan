"""Investment import: QIF parsing, Cash action subtypes, CSV prices, dedup."""

from datetime import date

import pytest

from finance.services.investment_import import (
    parse_investment_qif,
    parse_price_csv,
    _content_hash,
    _map_cash_action,
    _parse_cents,
    _parse_micros,
)


# ---------------------------------------------------------------------------
# Amount / quantity parsing
# ---------------------------------------------------------------------------


class TestParseCents:
    def test_positive(self):
        assert _parse_cents("12.34") == 1234

    def test_negative(self):
        assert _parse_cents("-50.00") == -5000

    def test_comma_separator(self):
        assert _parse_cents("1,234.56") == 123456

    def test_no_decimal(self):
        assert _parse_cents("100") == 10000

    def test_dollar_sign(self):
        assert _parse_cents("$99.99") == 9999

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_cents("")


class TestParseMicros:
    def test_integer(self):
        assert _parse_micros("50") == 50_000_000

    def test_three_decimals(self):
        assert _parse_micros("12.345") == 12_345_000

    def test_six_decimals(self):
        assert _parse_micros("1.123456") == 1_123_456

    def test_negative(self):
        assert _parse_micros("-5.5") == -5_500_000


# ---------------------------------------------------------------------------
# Cash action mapping (F12)
# ---------------------------------------------------------------------------


class TestCashActionMapping:
    def test_interest_income(self):
        assert _map_cash_action(1500, "Interest Inc", None) == "interest"

    def test_sweep_security_is_other(self):
        assert _map_cash_action(500, None, "SPAXX") == "other"

    def test_positive_no_context_is_cash_in(self):
        assert _map_cash_action(1000, None, None) == "cash_in"

    def test_negative_no_context_is_cash_out(self):
        assert _map_cash_action(-1000, None, None) == "cash_out"

    def test_zero_amount_skips(self):
        assert _map_cash_action(0, None, None) is None


# ---------------------------------------------------------------------------
# Content hash dedup
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self):
        h1 = _content_hash(date(2024, 1, 1), "buy", "AAPL", 100_000_000, -500000)
        h2 = _content_hash(date(2024, 1, 1), "buy", "AAPL", 100_000_000, -500000)
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _content_hash(date(2024, 1, 1), "buy", "AAPL", 100_000_000, -500000)
        h2 = _content_hash(date(2024, 1, 2), "buy", "AAPL", 100_000_000, -500000)
        assert h1 != h2

    def test_32_char_hex(self):
        h = _content_hash(date(2024, 1, 1), "buy", "AAPL", 100, 100)
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# QIF investment parsing — synthetic fixture
# ---------------------------------------------------------------------------


SYNTHETIC_QIF = """\
!Account
NTest Brokerage
TInvst
^
!Type:Security
NACME Corp
SACME
TStock
^
!Type:Security
NMoney Market Sweep
TOther
^
!Type:Invst
D01/15/2024
NBuy
YACME Corp
I50.00
Q100
T-5,000.00
O10.00
^
!Type:Invst
D04/01/2024
NReinvDiv
YACME Corp
I52.00
Q3.846154
T200.00
^
!Type:Invst
D07/01/2024
NSell
YACME Corp
I55.00
Q50
T2,750.00
^
!Type:Invst
D03/15/2024
NDiv
YACME Corp
T150.00
MQuarterly dividend
^
!Type:Invst
D06/01/2024
NShrsIn
YACME Corp
Q200
^
!Type:Invst
D08/01/2024
NStkSplit
YACME Corp
Q600
^
!Type:Invst
D09/01/2024
NCash
T38.50
LInterest Inc
^
!Type:Invst
D09/02/2024
NCash
T0.00
^
!Type:Invst
D09/03/2024
NWeirdAction
T100.00
^
!Type:Prices
"ACME",55.25," 9/ 1/2024"
"ACME",56.00," 9/15/2024"
^
"""


class TestParseInvestmentQIF:
    def test_parses_securities(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        assert len(result.securities) == 2
        assert result.securities[0].name == "ACME Corp"
        assert result.securities[0].symbol == "ACME"
        assert result.securities[0].security_type == "stock"
        assert result.securities[1].name == "Money Market Sweep"
        assert result.securities[1].security_type == "other"

    def test_parses_buy(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        buys = [c for c in result.candidates if c.action == "buy"]
        assert len(buys) == 1
        b = buys[0]
        assert b.trade_date == date(2024, 1, 15)
        assert b.security_name == "ACME Corp"
        assert b.quantity_micros == 100_000_000
        assert b.price_micros == 50_000_000
        assert b.amount_cents == -500_000
        assert b.fee_cents == 1000

    def test_parses_reinvest_dividend(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        reinvs = [c for c in result.candidates if c.action == "reinvest_dividend"]
        assert len(reinvs) == 1
        r = reinvs[0]
        assert r.quantity_micros == 3_846_154
        assert r.amount_cents == 20_000

    def test_parses_sell(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        sells = [c for c in result.candidates if c.action == "sell"]
        assert len(sells) == 1
        assert sells[0].amount_cents == 275_000

    def test_parses_dividend(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        divs = [c for c in result.candidates if c.action == "dividend"]
        assert len(divs) == 1
        assert divs[0].amount_cents == 15_000
        assert divs[0].memo == "Quarterly dividend"

    def test_parses_shares_in(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        shrs = [c for c in result.candidates if c.action == "shares_in"]
        assert len(shrs) == 1
        assert shrs[0].quantity_micros == 200_000_000

    def test_parses_split(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        splits = [c for c in result.candidates if c.action == "split"]
        assert len(splits) == 1
        assert splits[0].quantity_micros == 600_000_000

    def test_cash_interest_mapped(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        interests = [c for c in result.candidates if c.action == "interest"]
        assert len(interests) == 1
        assert interests[0].amount_cents == 3850

    def test_zero_amount_cash_skipped(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        # The Cash record with T0.00 should be skipped
        assert result.skipped_count >= 1

    def test_unknown_action_errors(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        unknown_errors = [e for e in result.errors if "Unknown" in e]
        assert len(unknown_errors) == 1
        assert "WeirdAction" in unknown_errors[0]

    def test_parses_prices(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        assert len(result.prices) == 2
        assert result.prices[0].security_name == "ACME"
        assert result.prices[0].price_micros == 55_250_000
        assert result.prices[0].date == date(2024, 9, 1)

    def test_account_key_set(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        for c in result.candidates:
            assert c.account_key == "Test Brokerage"

    def test_external_ids_unique(self):
        result = parse_investment_qif(SYNTHETIC_QIF)
        ids = [c.external_id for c in result.candidates]
        assert len(ids) == len(set(ids))

    def test_idempotent_parse(self):
        """Parsing the same file twice produces identical candidates."""
        r1 = parse_investment_qif(SYNTHETIC_QIF)
        r2 = parse_investment_qif(SYNTHETIC_QIF)
        assert len(r1.candidates) == len(r2.candidates)
        for c1, c2 in zip(r1.candidates, r2.candidates):
            assert c1.external_id == c2.external_id
            assert c1.action == c2.action
            assert c1.amount_cents == c2.amount_cents


# ---------------------------------------------------------------------------
# Transfer account detection
# ---------------------------------------------------------------------------


TRANSFER_QIF = """\
!Type:Invst
D01/15/2024
NXOut
T-5000.00
L[Checking Account]
^
"""


class TestTransferDetection:
    def test_xout_with_transfer_account(self):
        result = parse_investment_qif(TRANSFER_QIF)
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.action == "cash_out"
        assert c.transfer_account == "Checking Account"


# ---------------------------------------------------------------------------
# Minimal / edge-case QIF
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string(self):
        result = parse_investment_qif("")
        assert len(result.candidates) == 0
        assert len(result.errors) == 0

    def test_no_investment_blocks(self):
        result = parse_investment_qif("!Type:Bank\nD01/01/2024\nT-50.00\n^\n")
        assert len(result.candidates) == 0

    def test_out_of_scope_action_skipped(self):
        qif = "!Type:Invst\nD01/01/2024\nNVest\nT1000.00\n^\n"
        result = parse_investment_qif(qif)
        assert len(result.candidates) == 0
        assert result.skipped_count == 1
        assert any("Out-of-scope" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Benchmark CSV parsing
# ---------------------------------------------------------------------------


class TestPriceCSV:
    def test_yahoo_format(self):
        csv = "Date,Open,High,Low,Close,Adj Close,Volume\n2024-01-02,100.00,102.00,99.50,101.50,101.50,1000000\n2024-01-03,101.50,103.00,101.00,102.75,102.75,1200000\n"
        result = parse_price_csv(csv, "SP500TR")
        assert len(result.prices) == 2
        assert result.prices[0].date == date(2024, 1, 2)
        assert result.prices[0].price_micros == 101_500_000
        assert result.prices[0].security_name == "SP500TR"
        assert result.prices[1].price_micros == 102_750_000

    def test_minimal_two_column(self):
        csv = "Date,Close\n2024-01-02,100.50\n2024-01-03,101.25\n"
        result = parse_price_csv(csv, "TEST")
        assert len(result.prices) == 2

    def test_adj_close_column(self):
        csv = "Date,Close,Adj Close\n2024-01-02,100.50,99.50\n"
        result = parse_price_csv(csv, "TEST")
        assert len(result.prices) == 1
        # Adj Close takes precedence (last matching column wins)
        assert result.prices[0].price_micros == 99_500_000

    def test_skips_null_values(self):
        csv = "Date,Close\n2024-01-02,null\n2024-01-03,101.25\n"
        result = parse_price_csv(csv, "TEST")
        assert len(result.prices) == 1

    def test_missing_header_errors(self):
        csv = "Foo,Bar\n1,2\n"
        result = parse_price_csv(csv, "TEST")
        assert len(result.errors) == 1
        assert "header" in result.errors[0].lower()

    def test_too_few_lines_errors(self):
        csv = "Date,Close\n"
        result = parse_price_csv(csv, "TEST")
        assert len(result.errors) == 1

    def test_stooq_date_format(self):
        csv = "Date,Close\n01/02/2024,100.50\n"
        result = parse_price_csv(csv, "TEST")
        assert len(result.prices) == 1
        assert result.prices[0].date == date(2024, 1, 2)

import unittest
from decimal import Decimal
from rebalancer import allocate_whole_shares, calculate_buy_only_rebalance
import config

class TestRebalancer(unittest.TestCase):
    def test_all_cash_new_portfolio(self):
        """When portfolio is empty, cash should split according to target weights."""
        current_positions = {}
        cash = Decimal("1000.00")
        results = calculate_buy_only_rebalance(current_positions, cash, config.TARGET_PORTFOLIO)
        
        self.assertEqual(results["AVLV"]["allocated_cash"], Decimal("450.00"))
        self.assertEqual(results["DFAI"]["allocated_cash"], Decimal("250.00"))
        self.assertEqual(results["AVUV"]["allocated_cash"], Decimal("150.00"))
        self.assertEqual(results["AVDV"]["allocated_cash"], Decimal("100.00"))
        self.assertEqual(results["DFEM"]["allocated_cash"], Decimal("50.00"))
        self.assertEqual(sum(r["allocated_cash"] for r in results.values()), cash)

    def test_rebalance_underweight_positions(self):
        """When AVLV is heavily overperforming, cash should be routed to underweight tickers."""
        # Suppose AVLV grew to $900, others stay at $0. Cash available: $1000.
        # Total portfolio will be $1900.
        # Targets: AVLV 45% = $855, DFAI 25% = $475, AVUV 15% = $285, AVDV 10% = $190, DFEM 5% = $95.
        # AVLV current ($900) > Target ($855), so AVLV shortfall = 0.
        # All $1000 cash should be distributed to DFAI, AVUV, AVDV, DFEM!
        current_positions = {
            "AVLV": Decimal("900.00"),
            "DFAI": Decimal("0.00"),
            "AVUV": Decimal("0.00"),
            "AVDV": Decimal("0.00"),
            "DFEM": Decimal("0.00")
        }
        cash = Decimal("1000.00")
        results = calculate_buy_only_rebalance(current_positions, cash, config.TARGET_PORTFOLIO)
        
        # AVLV should get $0 allocated!
        self.assertEqual(results["AVLV"]["allocated_cash"], Decimal("0.00"))
        # Total cash spent must equal $1000
        self.assertEqual(sum(r["allocated_cash"] for r in results.values()), cash)
        
    def test_penny_rounding(self):
        """Ensure cash sum matches exact available cash even with rounding."""
        current_positions = {}
        cash = Decimal("123.45")
        results = calculate_buy_only_rebalance(current_positions, cash, config.TARGET_PORTFOLIO)
        self.assertEqual(sum(r["allocated_cash"] for r in results.values()), cash)


class TestAllocateWholeShares(unittest.TestCase):
    TARGETS = {"AAA": Decimal("0.60"), "BBB": Decimal("0.40")}

    def _plan(self, positions, cash):
        return calculate_buy_only_rebalance(positions, cash, self.TARGETS)

    def test_floors_to_whole_shares_then_sweeps_residual(self):
        positions = {}
        cash = Decimal("1000.00")
        quotes = {"AAA": Decimal("70.00"), "BBB": Decimal("30.00")}
        shares = allocate_whole_shares(self._plan(positions, cash), positions, cash, quotes, self.TARGETS)

        # $600 / $70 -> 8 shares ($560), $400 / $30 -> 13 shares ($390).
        # The $50 left can't buy AAA ($70), so the sweep buys one more BBB.
        self.assertEqual(shares, {"AAA": 8, "BBB": 14})
        spent = sum(shares[t] * quotes[t] for t in shares)
        self.assertLessEqual(spent, cash)
        self.assertLess(cash - spent, min(quotes.values()))

    def test_never_overspends(self):
        positions = {"AAA": Decimal("5000"), "BBB": Decimal("100")}
        cash = Decimal("123.45")
        quotes = {"AAA": Decimal("41.17"), "BBB": Decimal("19.99")}
        shares = allocate_whole_shares(self._plan(positions, cash), positions, cash, quotes, self.TARGETS)
        spent = sum(shares[t] * quotes[t] for t in shares)
        self.assertLessEqual(spent, cash)
        self.assertLess(cash - spent, min(quotes.values()))

    def test_missing_quote_gets_zero_shares(self):
        positions = {}
        cash = Decimal("500")
        quotes = {"AAA": Decimal("50")}
        shares = allocate_whole_shares(self._plan(positions, cash), positions, cash, quotes, self.TARGETS)
        self.assertEqual(shares["BBB"], 0)
        self.assertLessEqual(shares["AAA"] * quotes["AAA"], cash)

    def test_cash_below_cheapest_share_buys_nothing(self):
        positions = {}
        cash = Decimal("20")
        quotes = {"AAA": Decimal("50"), "BBB": Decimal("25")}
        shares = allocate_whole_shares(self._plan(positions, cash), positions, cash, quotes, self.TARGETS)
        self.assertEqual(shares, {"AAA": 0, "BBB": 0})


if __name__ == "__main__":
    unittest.main()

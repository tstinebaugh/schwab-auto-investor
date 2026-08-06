import unittest
from decimal import Decimal
from rebalancer import calculate_buy_only_rebalance
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

if __name__ == "__main__":
    unittest.main()

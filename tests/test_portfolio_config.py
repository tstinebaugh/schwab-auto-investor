import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import config
from config import validate_portfolio, load_portfolio_config


class TestPortfolioConfig(unittest.TestCase):
    def test_validate_portfolio_percentages(self):
        raw = {
            "AVLV": 45,
            "DFAI": 25,
            "AVUV": 15,
            "AVDV": 10,
            "DFEM": 5
        }
        res = validate_portfolio(raw)
        self.assertEqual(res["AVLV"], Decimal("0.45"))
        self.assertEqual(res["DFAI"], Decimal("0.25"))
        self.assertEqual(res["AVUV"], Decimal("0.15"))
        self.assertEqual(res["AVDV"], Decimal("0.10"))
        self.assertEqual(res["DFEM"], Decimal("0.05"))
        self.assertEqual(sum(res.values()), Decimal("1.0"))

    def test_validate_portfolio_percentages_with_strings(self):
        raw = {
            "AVLV": "45%",
            "DFAI": "25%",
            "AVUV": "15%",
            "AVDV": "10%",
            "DFEM": "5%"
        }
        res = validate_portfolio(raw)
        self.assertEqual(sum(res.values()), Decimal("1.0"))
        self.assertEqual(res["AVLV"], Decimal("0.45"))

    def test_validate_portfolio_decimals(self):
        raw = {
            "AVLV": 0.45,
            "DFAI": 0.25,
            "AVUV": 0.15,
            "AVDV": 0.10,
            "DFEM": 0.05
        }
        res = validate_portfolio(raw)
        self.assertEqual(res["AVLV"], Decimal("0.45"))
        self.assertEqual(sum(res.values()), Decimal("1.0"))

    def test_validate_portfolio_invalid_sum_percentages(self):
        raw = {
            "AVLV": 40,
            "DFAI": 20
        }
        with self.assertRaises(ValueError) as ctx:
            validate_portfolio(raw)
        self.assertIn("must sum to 100%", str(ctx.exception))

    def test_validate_portfolio_invalid_sum_decimals(self):
        raw = {
            "AVLV": 0.40,
            "DFAI": 0.20
        }
        with self.assertRaises(ValueError) as ctx:
            validate_portfolio(raw)
        self.assertIn("must sum to 1.0 or 100%", str(ctx.exception))

    def test_validate_portfolio_negative_weight(self):
        raw = {
            "AVLV": -10,
            "DFAI": 110
        }
        with self.assertRaises(ValueError) as ctx:
            validate_portfolio(raw)
        self.assertIn("must be greater than 0", str(ctx.exception))

    def test_validate_portfolio_zero_weight(self):
        raw = {
            "AVLV": 0,
            "DFAI": 100
        }
        with self.assertRaises(ValueError) as ctx:
            validate_portfolio(raw)
        self.assertIn("must be greater than 0", str(ctx.exception))

    def test_validate_portfolio_ticker_normalization(self):
        raw = {
            "avlv": 50,
            "dfai": 50
        }
        res = validate_portfolio(raw)
        self.assertIn("AVLV", res)
        self.assertIn("DFAI", res)

    def test_validate_portfolio_invalid_ticker_symbols(self):
        invalid_tickers = ["AV LV", "$AVUV", "DFEM!", "", "   ", "@ETF", "AV#LV"]
        for bad_ticker in invalid_tickers:
            raw = {bad_ticker: 100}
            with self.assertRaises(ValueError):
                validate_portfolio(raw)

    def test_validate_portfolio_valid_ticker_formats(self):
        raw = {
            "BRK.B": 50,
            "BF-B": 50
        }
        res = validate_portfolio(raw)
        self.assertEqual(res["BRK.B"], Decimal("0.50"))
        self.assertEqual(res["BF-B"], Decimal("0.50"))

    def test_load_portfolio_config_from_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"VTI": 80, "VXUS": 20}, f)
            temp_path = f.name

        try:
            res = load_portfolio_config(temp_path)
            self.assertEqual(res["VTI"], Decimal("0.80"))
            self.assertEqual(res["VXUS"], Decimal("0.20"))
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_load_portfolio_config_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_portfolio_config("non_existent_portfolio_file_12345.json")

    def test_load_portfolio_config_default_file(self):
        # Should load the root portfolio.json
        res = load_portfolio_config(None)
        self.assertIn("AVLV", res)
        self.assertEqual(sum(res.values()), Decimal("1.0"))

    def test_validate_portfolio_non_dict_and_empty(self):
        with self.assertRaises(ValueError):
            validate_portfolio([])
        with self.assertRaises(ValueError):
            validate_portfolio({})
        with self.assertRaises(ValueError):
            validate_portfolio("not_a_dict")


if __name__ == "__main__":
    unittest.main()

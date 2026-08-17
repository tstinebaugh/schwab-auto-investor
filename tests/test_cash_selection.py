import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

import main


class TestCashSelection(unittest.TestCase):
    @patch("main.get_schwab_client")
    @patch("main.keychain_manager.has_credentials")
    @patch("main.check_vpn_guardrail")
    @patch("main.SchwabTrader")
    def test_handle_rebalance_default_uses_ledger_cash(self, mock_trader_cls, mock_check_vpn, mock_has_creds, mock_get_client):
        mock_has_creds.return_value = True
        mock_trader = MagicMock()
        mock_trader_cls.return_value = mock_trader

        # Account summary with 0 settled cash but $1000 ledger cash
        mock_trader.get_account_summary.return_value = {
            "settled_cash": Decimal("0.00"),
            "ledger_cash": Decimal("1000.00"),
            "target_holdings": {"SCHB": Decimal("0.00")},
            "all_holdings": {"SCHB": Decimal("0.00")}
        }
        mock_trader.get_quotes.return_value = {"SCHB": Decimal("50.00")}

        args = MagicMock()
        args.portfolio = None
        args.settled_only = False
        args.dry_run = True
        args.gtc_limit = False
        args.price_cap_pct = 5.0
        args.bypass_vpn = True

        with patch("builtins.print") as mock_print:
            main.handle_rebalance(args)
            # Default should proceed using ledger_cash ($1000.00)
            mock_trader.get_quotes.assert_called_once()
            printed_output = " ".join([str(call.args[0]) for call in mock_print.call_args_list if call.args])
            self.assertIn("Cash Available for Rebalancing (cashBalance): $1,000.00", printed_output)

    @patch("main.get_schwab_client")
    @patch("main.keychain_manager.has_credentials")
    @patch("main.check_vpn_guardrail")
    @patch("main.SchwabTrader")
    def test_handle_rebalance_settled_only_flag(self, mock_trader_cls, mock_check_vpn, mock_has_creds, mock_get_client):
        mock_has_creds.return_value = True
        mock_trader = MagicMock()
        mock_trader_cls.return_value = mock_trader

        mock_trader.get_account_summary.return_value = {
            "settled_cash": Decimal("0.00"),
            "ledger_cash": Decimal("1000.00"),
            "target_holdings": {"SCHB": Decimal("0.00")},
            "all_holdings": {"SCHB": Decimal("0.00")}
        }

        args = MagicMock()
        args.portfolio = None
        args.settled_only = True
        args.dry_run = True
        args.gtc_limit = False
        args.price_cap_pct = 5.0
        args.bypass_vpn = True

        with patch("builtins.print") as mock_print:
            main.handle_rebalance(args)
            # Should skip because settled_cash is 0 in settled-only mode
            mock_trader.get_quotes.assert_not_called()
            printed_output = " ".join([str(call.args[0]) for call in mock_print.call_args_list if call.args])
            self.assertIn("below minimum threshold", printed_output)


if __name__ == "__main__":
    unittest.main()

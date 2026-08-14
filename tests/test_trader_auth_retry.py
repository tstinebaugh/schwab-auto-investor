import unittest
from unittest.mock import MagicMock, patch
import httpx
from trader import SchwabTrader


class TestTraderAuthRetry(unittest.TestCase):
    @patch("trader.keychain_manager.get_credential")
    @patch("trader.get_schwab_client")
    def test_call_api_retry_on_503_oauth_error(self, mock_get_schwab_client, mock_get_credential):
        mock_get_credential.return_value = "dummy_account_hash"

        # Initial client fails on get_account due to 503 on OAuth token refresh
        initial_client = MagicMock()
        req = MagicMock(url="https://api.schwabapi.com/v1/oauth/token")
        resp_503 = MagicMock(status_code=503)
        initial_client.get_account.side_effect = httpx.HTTPStatusError("503 Service Unavailable", request=req, response=resp_503)

        # Fresh client succeeds on retry
        fresh_client = MagicMock()
        successful_resp = MagicMock(status_code=200)
        successful_resp.json.return_value = {
            "securitiesAccount": {
                "currentBalances": {"cashBalance": 1000.0},
                "positions": []
            }
        }
        fresh_client.get_account.return_value = successful_resp
        mock_get_schwab_client.return_value = fresh_client

        trader = SchwabTrader(client=initial_client, account_hash="dummy_hash")
        summary = trader.get_account_summary()

        # Verify automatic re-authentication was triggered and fresh client used
        mock_get_schwab_client.assert_called_once_with(force_reauth=True)
        fresh_client.get_account.assert_called_once()
        self.assertEqual(summary["ledger_cash"], 1000.0)


if __name__ == "__main__":
    unittest.main()

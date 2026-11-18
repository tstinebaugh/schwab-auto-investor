import unittest
from unittest.mock import MagicMock, patch
import httpx
from auth_manager import InteractiveAuthRequired, is_auth_error, get_schwab_client

try:
    from authlib.oauth2.rfc6749.errors import OAuth2Error
except ImportError:
    OAuth2Error = Exception


class TestAuthManager(unittest.TestCase):
    def test_is_auth_error_http_status_codes(self):
        # 401 Unauthorized
        resp_401 = MagicMock(status_code=401)
        req = MagicMock(url="https://api.schwabapi.com/v1/accounts")
        err_401 = httpx.HTTPStatusError("401 Unauthorized", request=req, response=resp_401)
        self.assertTrue(is_auth_error(err_401))

        # 403 Forbidden
        resp_403 = MagicMock(status_code=403)
        err_403 = httpx.HTTPStatusError("403 Forbidden", request=req, response=resp_403)
        self.assertTrue(is_auth_error(err_403))

        # 503 on oauth/token endpoint
        resp_503 = MagicMock(status_code=503)
        req_token = MagicMock(url="https://api.schwabapi.com/v1/oauth/token")
        err_token_503 = httpx.HTTPStatusError("503 Service Unavailable", request=req_token, response=resp_503)
        self.assertTrue(is_auth_error(err_token_503))

    def test_is_auth_error_oauth_exceptions(self):
        class MockOAuthError(OAuth2Error):
            pass
        self.assertTrue(is_auth_error(MockOAuthError("invalid_grant")))

    def test_is_auth_error_string_fallbacks(self):
        self.assertTrue(is_auth_error(Exception("Token expired or unauthorized")))
        self.assertFalse(is_auth_error(Exception("Network timeout connecting to server")))

    @patch("auth_manager.sys.stdin")
    @patch("auth_manager.keychain_manager.get_all_credentials")
    @patch("auth_manager.schwab.auth.client_from_manual_flow")
    @patch("auth_manager.config.TOKEN_PATH")
    def test_get_schwab_client_force_reauth(self, mock_token_path, mock_manual_flow, mock_creds, mock_stdin):
        mock_stdin.isatty.return_value = True
        mock_creds.return_value = {
            "app_key": "test_key",
            "app_secret": "test_secret",
            "callback_url": "https://127.0.0.1"
        }
        mock_token_path.exists.return_value = True

        client = get_schwab_client(force_reauth=True)

        mock_token_path.unlink.assert_called_once()
        mock_manual_flow.assert_called_once()

    @patch("auth_manager.sys.stdin")
    @patch("auth_manager.keychain_manager.get_all_credentials")
    @patch("auth_manager.schwab.auth.client_from_manual_flow")
    @patch("auth_manager.config.TOKEN_PATH")
    def test_get_schwab_client_non_interactive_fails_fast(self, mock_token_path, mock_manual_flow, mock_creds, mock_stdin):
        """Under cron there is no terminal to paste the OAuth redirect URL into, so don't hang."""
        mock_stdin.isatty.return_value = False
        mock_creds.return_value = {"app_key": "k", "app_secret": "s", "callback_url": "https://127.0.0.1"}
        mock_token_path.exists.return_value = False

        with self.assertRaises(InteractiveAuthRequired):
            get_schwab_client()
        mock_manual_flow.assert_not_called()


if __name__ == "__main__":
    unittest.main()

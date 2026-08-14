import os
import sys
from pathlib import Path
import httpx
import schwab
import keychain_manager
import config

try:
    from authlib.oauth2.rfc6749.errors import OAuth2Error
except ImportError:
    OAuth2Error = Exception


def is_auth_error(exc: Exception) -> bool:
    """
    Checks if an exception is an authentication or OAuth token failure/expiration.
    """
    if isinstance(exc, OAuth2Error):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response is not None and exc.response.status_code in (401, 403):
            return True
        if exc.request is not None and "oauth/token" in str(exc.request.url):
            return True

    exc_str = str(exc).lower()
    if any(term in exc_str for term in ("401", "403", "unauthorized", "invalid_grant", "access_denied")):
        return True
    if "oauth/token" in exc_str or ("token" in exc_str and ("expired" in exc_str or "invalid" in exc_str or "refresh" in exc_str)):
        return True

    return False


def get_schwab_client(force_reauth: bool = False):
    """
    Initializes and returns an authenticated schwab client using Keychain credentials
    and saved token. Prompts for manual OAuth authentication if token is missing, expired,
    corrupt, or if force_reauth is True.
    """
    creds = keychain_manager.get_all_credentials()
    app_key = creds.get("app_key")
    app_secret = creds.get("app_secret")
    callback_url = creds.get("callback_url") or config.DEFAULT_CALLBACK_URL

    if not app_key or not app_secret:
        raise ValueError(
            "Missing Schwab API Key or Secret in Keychain. "
            "Please run 'python main.py setup' first to store your credentials."
        )

    # Ensure token directory exists
    config.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    token_path = config.TOKEN_PATH

    if force_reauth and token_path.exists():
        try:
            token_path.unlink()
            print("[INFO] Cleared old OAuth token file for re-authentication.")
        except Exception as e:
            print(f"[WARNING] Could not delete existing token file: {e}")

    # Try loading existing token
    if not force_reauth and token_path.exists():
        try:
            client = schwab.auth.client_from_token_file(
                token_path=str(token_path),
                api_key=app_key,
                app_secret=app_secret
            )
            return client
        except Exception as e:
            print(f"Token file load failed or token expired ({e}). Starting re-authentication flow...")

    # Manual authorization flow
    print("\n--- Schwab API OAuth Authentication / Token Refresh ---")
    print("1. A browser window or URL will open for Schwab login.")
    print("2. Log in and approve access for your application.")
    print(f"3. Schwab will redirect your browser to {callback_url}?code=...")
    print("4. Copy the entire redirected URL from your browser address bar and paste it below.\n")

    client = schwab.auth.client_from_manual_flow(
        api_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=str(token_path)
    )
    print("\n[SUCCESS] Schwab authentication successful! OAuth token saved.")
    return client


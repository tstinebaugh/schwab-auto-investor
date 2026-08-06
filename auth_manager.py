import os
import sys
from pathlib import Path
import schwab
import keychain_manager
import config

def get_schwab_client():
    """
    Initializes and returns an authenticated schwab client using Keychain credentials
    and saved token. Prompts for manual OAuth authentication if token is missing or expired.
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
    token_path = str(config.TOKEN_PATH)

    # Try loading existing token
    if os.path.exists(token_path):
        try:
            client = schwab.auth.client_from_token_file(
                token_path=token_path,
                api_key=app_key,
                app_secret=app_secret
            )
            return client
        except Exception as e:
            print(f"Token file load failed or token expired ({e}). Starting re-authentication flow...")

    # Manual authorization flow
    print("\n--- Schwab API First-Time Authorization ---")
    print("1. A browser window or URL will open for Schwab login.")
    print("2. Log in and approve access for your application.")
    print(f"3. Schwab will redirect your browser to {callback_url}?code=...")
    print("4. Copy the entire redirected URL from your browser address bar and paste it below.\n")

    client = schwab.auth.client_from_manual_flow(
        api_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=token_path
    )
    print("\n[SUCCESS] Schwab authentication successful! OAuth token saved.")
    return client

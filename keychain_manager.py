import keyring
import getpass
import sys
from typing import Dict, Optional
import config

USERNAME = getpass.getuser()

def set_credential(key_name: str, value: str) -> None:
    """Store a secret in macOS Keychain."""
    keyring.set_password(key_name, USERNAME, value)

def get_credential(key_name: str) -> Optional[str]:
    """Retrieve a secret from macOS Keychain."""
    return keyring.get_password(key_name, USERNAME)

def delete_credential(key_name: str) -> None:
    """Delete a secret from macOS Keychain."""
    try:
        keyring.delete_password(key_name, USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass

def save_all_credentials(
    app_key: str,
    app_secret: str,
    account_hash: str,
    callback_url: str = config.DEFAULT_CALLBACK_URL
) -> None:
    """Save all Schwab API credentials to macOS Keychain."""
    set_credential(config.KEY_APP_KEY, app_key.strip())
    set_credential(config.KEY_APP_SECRET, app_secret.strip())
    set_credential(config.KEY_ACCOUNT_HASH, account_hash.strip())
    set_credential(config.KEY_CALLBACK_URL, callback_url.strip())

def get_all_credentials() -> Dict[str, Optional[str]]:
    """Fetch all credentials from macOS Keychain."""
    return {
        "app_key": get_credential(config.KEY_APP_KEY),
        "app_secret": get_credential(config.KEY_APP_SECRET),
        "account_hash": get_credential(config.KEY_ACCOUNT_HASH),
        "callback_url": get_credential(config.KEY_CALLBACK_URL) or config.DEFAULT_CALLBACK_URL
    }

def has_credentials() -> bool:
    """Check if mandatory credentials exist in macOS Keychain."""
    creds = get_all_credentials()
    return bool(creds["app_key"] and creds["app_secret"])

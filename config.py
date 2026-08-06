from decimal import Decimal
import os
from pathlib import Path

# Target ETF Portfolio Allocation (Must sum to 1.0)
TARGET_PORTFOLIO = {
    "AVLV": Decimal("0.45"),
    "DFAI": Decimal("0.25"),
    "AVUV": Decimal("0.15"),
    "AVDV": Decimal("0.10"),
    "DFEM": Decimal("0.05")
}

# Execution guardrails
MIN_CASH_THRESHOLD = Decimal("10.00")  # Minimum cash needed to run trades

# Keychain service identifiers
KEYRING_SERVICE_PREFIX = "schwab_investor"
KEY_APP_KEY = f"{KEYRING_SERVICE_PREFIX}_app_key"
KEY_APP_SECRET = f"{KEYRING_SERVICE_PREFIX}_app_secret"
KEY_ACCOUNT_HASH = f"{KEYRING_SERVICE_PREFIX}_account_hash"
KEY_CALLBACK_URL = f"{KEYRING_SERVICE_PREFIX}_callback_url"

# Default Callback URL for local apps (Must match what is registered in Schwab Developer Portal)
DEFAULT_CALLBACK_URL = "https://127.0.0.1"

# OAuth Token Storage Path
TOKEN_DIR = Path.home() / ".schwab"
TOKEN_PATH = TOKEN_DIR / "token.json"

def is_market_open() -> tuple[bool, str]:
    """
    Checks if US Stock Market is open for regular trading hours (9:30 AM - 4:00 PM ET).
    Returns (is_open_for_trading, status_reason).
    """
    from datetime import datetime
    import zoneinfo

    et_tz = zoneinfo.ZoneInfo("America/New_York")
    now_et = datetime.now(et_tz)

    if now_et.weekday() >= 5:
        return (False, "Market is CLOSED (Weekend)")

    trading_start = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    if trading_start <= now_et <= market_close:
        return (True, "Market is OPEN for continuous trading")
    else:
        return (False, "Market is CLOSED (Outside 9:30 AM - 4:00 PM ET)")

def check_us_vpn() -> tuple[bool, str]:
    """Verifies that the current public IP address is located in the US (VPN protection)."""
    import urllib.request
    import json

    try:
        req = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            country = data.get("country_code", "").upper()
            ip = data.get("ip", "Unknown")
            city = data.get("city", "")
            region = data.get("region", "")
            location_str = f"{city}, {region} ({country}) [IP: {ip}]"
            return (country == "US", location_str)
    except Exception as e:
        # Fallback check via ipinfo.io
        try:
            req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                country = data.get("country", "").upper()
                ip = data.get("ip", "Unknown")
                return (country == "US", f"IP: {ip} ({country})")
        except Exception:
            return (False, f"Failed to verify IP location ({e})")



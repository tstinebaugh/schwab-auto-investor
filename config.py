import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Union

# Default Target ETF Portfolio Allocation (Must sum to 1.0)
DEFAULT_TARGET_PORTFOLIO: Dict[str, Decimal] = {
    "AVLV": Decimal("0.45"),
    "DFAI": Decimal("0.25"),
    "AVUV": Decimal("0.15"),
    "AVDV": Decimal("0.10"),
    "DFEM": Decimal("0.05")
}

TARGET_PORTFOLIO = DEFAULT_TARGET_PORTFOLIO
DEFAULT_PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"

TICKER_REGEX = re.compile(r"^[A-Z0-9.\-]+$")


def validate_portfolio(portfolio_raw: dict) -> Dict[str, Decimal]:
    """
    Validates and normalizes portfolio allocations.
    Accepts dictionary of {ticker: weight} where weights can be percentages (e.g., 45, "45%")
    or decimal proportions (e.g., 0.45).
    Ensures:
      1. Tickers are valid uppercase exchange symbols.
      2. Weights are positive numbers.
      3. Total allocation sums to 100% (or 1.0).
    Returns normalized Dict[str, Decimal] summing exactly to 1.0.
    """
    if not isinstance(portfolio_raw, dict) or not portfolio_raw:
        raise ValueError("Portfolio configuration must be a non-empty JSON object mapping tickers to weights.")

    parsed_weights: Dict[str, Decimal] = {}

    for raw_ticker, raw_weight in portfolio_raw.items():
        if not isinstance(raw_ticker, str):
            raise ValueError(f"Invalid ticker key '{raw_ticker}': must be a string.")
        
        ticker = raw_ticker.strip().upper()
        if not ticker or not TICKER_REGEX.match(ticker):
            raise ValueError(f"Invalid ticker symbol '{raw_ticker}'. Tickers must contain only alphanumeric characters, dots, or hyphens.")

        # Parse weight value
        try:
            if isinstance(raw_weight, str):
                cleaned_weight = raw_weight.strip().rstrip("%")
                weight_dec = Decimal(cleaned_weight)
            elif isinstance(raw_weight, (int, float, Decimal)):
                weight_dec = Decimal(str(raw_weight))
            else:
                raise ValueError(f"Unsupported weight type for {ticker}: {type(raw_weight).__name__}")
        except Exception as e:
            raise ValueError(f"Invalid weight '{raw_weight}' for ticker '{ticker}': {e}")

        if weight_dec <= Decimal("0"):
            raise ValueError(f"Target weight for ticker '{ticker}' must be greater than 0 (got {weight_dec}).")

        parsed_weights[ticker] = weight_dec

    total_weight = sum(parsed_weights.values())

    # Detect whether inputs were specified in percentage (e.g., sum ~ 100) or decimal (sum ~ 1.0)
    if total_weight > Decimal("1.5"):
        # Percentage format (expecting 100.0)
        if abs(total_weight - Decimal("100.0")) > Decimal("0.01"):
            raise ValueError(f"Portfolio target percentages must sum to 100% (currently sums to {total_weight}%).")
        # Normalize to 1.0
        normalized = {t: w / Decimal("100") for t, w in parsed_weights.items()}
    else:
        # Decimal format (expecting 1.0)
        if abs(total_weight - Decimal("1.0")) > Decimal("0.0001"):
            raise ValueError(f"Portfolio target weights must sum to 1.0 or 100% (currently sums to {total_weight}).")
        normalized = parsed_weights

    # Ensure final sum matches Decimal("1.0") exactly
    norm_total = sum(normalized.values())
    diff = Decimal("1.0") - norm_total
    if diff != Decimal("0"):
        max_ticker = max(normalized.keys(), key=lambda t: normalized[t])
        normalized[max_ticker] += diff

    return normalized


def load_portfolio_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Decimal]:
    """
    Loads and validates portfolio allocation from a JSON file.
    If config_path is None, attempts to load 'portfolio.json' in the project root.
    If 'portfolio.json' does not exist and no path is passed, returns DEFAULT_TARGET_PORTFOLIO.
    """
    if config_path is None:
        target_file = DEFAULT_PORTFOLIO_FILE
        if not target_file.exists():
            return DEFAULT_TARGET_PORTFOLIO.copy()
    else:
        target_file = Path(config_path)
        if not target_file.exists():
            raise FileNotFoundError(f"Portfolio configuration file not found: {target_file}")

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in portfolio configuration file '{target_file}': {e}")
    except Exception as e:
        raise ValueError(f"Failed to read portfolio configuration file '{target_file}': {e}")

    return validate_portfolio(data)


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
    """Verifies that the current connection is located in the US (VPN protection)."""
    import urllib.request
    import json

    try:
        req = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            country = data.get("country_code", "").upper()
            city = data.get("city", "")
            region = data.get("region", "")
            loc_parts = [p for p in (city, region, country) if p]
            return (country == "US", ", ".join(loc_parts) or f"Country: {country}")
    except Exception as e:
        # Fallback check via ipinfo.io
        try:
            req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                country = data.get("country", "").upper()
                city = data.get("city", "")
                region = data.get("region", "")
                loc_parts = [p for p in (city, region, country) if p]
                return (country == "US", ", ".join(loc_parts) or f"Country: {country}")
        except Exception:
            return (False, f"Failed to verify connection location ({e})")



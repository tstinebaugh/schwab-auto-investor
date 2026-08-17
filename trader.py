from decimal import Decimal
from typing import Dict, Tuple, List, Optional, Any
import schwab
import keychain_manager
import config
from auth_manager import get_schwab_client, is_auth_error


class SchwabTrader:
    def __init__(self, client: schwab.client.Client, account_hash: Optional[str] = None):
        self.client = client
        self.account_hash = account_hash or keychain_manager.get_credential(config.KEY_ACCOUNT_HASH)
        
        if not self.account_hash:
            self.account_hash = self._fetch_and_save_account_hash()

    def _call_api(self, method_name: str, *args, **kwargs):
        """
        Executes a Schwab client API method with automatic retry and re-authentication 
        if an auth or token refresh error occurs.
        """
        try:
            method = getattr(self.client, method_name)
            resp = method(*args, **kwargs)
            if hasattr(resp, "status_code") and resp.status_code in (401, 403):
                raise RuntimeError(f"Schwab API returned HTTP status {resp.status_code} (Authentication Required)")
            return resp
        except Exception as e:
            if is_auth_error(e):
                print(f"\n[AUTH ERROR] Schwab authentication failure or token expired ({e}).")
                print("Initiating automatic re-authentication flow...\n")
                self.client = get_schwab_client(force_reauth=True)
                method = getattr(self.client, method_name)
                resp = method(*args, **kwargs)
                if hasattr(resp, "status_code") and resp.status_code in (401, 403):
                    raise RuntimeError(f"Schwab API returned HTTP status {resp.status_code} after re-authentication.")
                return resp
            raise

    def _fetch_and_save_account_hash(self) -> str:
        """Fetches account hashes from Schwab API and saves the primary account hash to Keychain."""
        resp = self._call_api("get_account_numbers")
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch account numbers from Schwab API (Status {resp.status_code}): {resp.text}")
        
        accounts = resp.json()
        if not accounts:
            raise ValueError("No brokerage accounts found for this Schwab login.")
        
        # Display available accounts
        print("\n--- SCHWAB ACCOUNTS DISCOVERED ---")
        for idx, acc in enumerate(accounts):
            acc_num = acc.get("accountNumber", "")
            masked_num = f"...{acc_num[-4:]}" if len(acc_num) > 4 else acc_num
            h_val = acc.get("hashValue")
            print(f"[{idx+1}] Account Number: {masked_num} -> Hash: {h_val}")
        
        # Use first account hash by default
        chosen_hash = accounts[0].get("hashValue")
        keychain_manager.set_credential(config.KEY_ACCOUNT_HASH, chosen_hash)
        primary_acc_num = accounts[0].get("accountNumber", "")
        primary_masked = f"...{primary_acc_num[-4:]}" if len(primary_acc_num) > 4 else primary_acc_num
        print(f"[AUTO-SAVED] Account Hash set to primary account ({primary_masked}) and stored in Keychain!\n")
        return chosen_hash


    def get_account_summary(self, target_portfolio: Optional[Dict[str, Decimal]] = None) -> Dict[str, Any]:
        """
        Fetches account balances and market values of target ETF holdings.
        Returns:
            Dict containing settled_cash, ledger_cash, buying_power, liquidation_value,
            target_holdings, and all_holdings.
        """
        if target_portfolio is None:
            target_portfolio = config.load_portfolio_config()

        resp = self._call_api(
            "get_account",
            self.account_hash,
            fields=schwab.client.Client.Account.Fields.POSITIONS
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch account info from Schwab API (Status {resp.status_code}): {resp.text}")

        account_data = resp.json()
        sec_account = account_data.get("securitiesAccount", {})
        
        current_balances = sec_account.get("currentBalances", {})
        initial_balances = sec_account.get("initialBalances", {})

        # Prefer cashAvailableForTrading or cashSettledFunds over raw ledger cashBalance
        cash_avail_raw = (
            current_balances.get("cashAvailableForTrading")
            if current_balances.get("cashAvailableForTrading") is not None
            else (
                current_balances.get("cashSettledFunds")
                if current_balances.get("cashSettledFunds") is not None
                else (
                    initial_balances.get("cashAvailableForTrading")
                    if initial_balances.get("cashAvailableForTrading") is not None
                    else current_balances.get("cashBalance", 0.0)
                )
            )
        )
        settled_cash = Decimal(str(cash_avail_raw if cash_avail_raw is not None else 0.0))
        ledger_cash = Decimal(str(current_balances.get("cashBalance", 0.0)))
        buying_power = Decimal(str(current_balances.get("buyingPower", 0.0)))
        liquidation_value = Decimal(str(current_balances.get("liquidationValue", 0.0)))

        # ETF positions (separate target portfolio vs non-target portfolio)
        positions = sec_account.get("positions", [])
        target_holdings: Dict[str, Decimal] = {t: Decimal("0.00") for t in target_portfolio}
        all_holdings: Dict[str, Decimal] = {}

        for pos in positions:
            instrument = pos.get("instrument", {})
            symbol = instrument.get("symbol")
            qty = Decimal(str(pos.get("longQuantity", 0)))
            mkt_val = Decimal(str(pos.get("marketValue", 0)))

            if symbol:
                all_holdings[symbol] = mkt_val
                if symbol in target_holdings:
                    target_holdings[symbol] = mkt_val

        summary = {
            "settled_cash": settled_cash,
            "ledger_cash": ledger_cash,
            "buying_power": buying_power,
            "liquidation_value": liquidation_value,
            "target_holdings": target_holdings,
            "all_holdings": all_holdings
        }

        return summary

    def get_quotes(self, symbols: List[str]) -> Dict[str, Decimal]:
        """Fetches current ask/last/close price for given ticker symbols."""
        resp = self._call_api("get_quotes", symbols)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch quotes from Schwab API (Status {resp.status_code}): {resp.text}")
        
        data = resp.json()
        quotes = {}
        for sym in symbols:
            quote_data = data.get(sym, {}).get("quote", {})
            ask = quote_data.get("askPrice")
            last = quote_data.get("lastPrice")
            close = quote_data.get("closePrice")
            
            price = last if (last and last > 0) else (close if (close and close > 0) else ask)
            quotes[sym] = Decimal(str(price or 0))
        return quotes

    def build_share_order_spec(self, ticker: str, shares: float) -> dict:
        """Builds standard equity market buy order spec using schwab-py."""
        return schwab.orders.equities.equity_buy_market(ticker, shares).build()

    def build_limit_order_spec(self, ticker: str, shares: float, limit_price: Decimal, gtc: bool = True) -> dict:
        """Builds equity limit buy order spec with GTC duration, NORMAL session for GTC, and price cap protection."""
        price_dec = Decimal(str(limit_price)).quantize(Decimal("0.01"))
        builder = schwab.orders.equities.equity_buy_limit(ticker, shares, str(price_dec))
        if gtc:
            builder.set_duration(schwab.orders.common.Duration.GOOD_TILL_CANCEL)
            # Schwab requires NORMAL session for GOOD_TILL_CANCEL orders; SEAMLESS session is rejected with GTC
            builder.set_session(schwab.orders.common.Session.NORMAL)
        else:
            builder.set_session(schwab.orders.common.Session.SEAMLESS)
        return builder.build()

    def place_order(self, order_spec: dict) -> bool:
        """Submits order to Schwab API and provides detailed error messages if rejected."""
        resp = self._call_api("place_order", self.account_hash, order_spec)
        if resp.status_code in (200, 201):
            return True
        else:
            error_details = resp.text
            try:
                err_json = resp.json()
                if isinstance(err_json, dict):
                    msg = err_json.get("message") or err_json.get("errorDetails") or err_json.get("errors")
                    if msg:
                        error_details = f"{msg} (Raw: {resp.text})"
            except Exception:
                pass
            raise RuntimeError(f"Order placement failed (Status {resp.status_code}): {error_details}")


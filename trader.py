from decimal import Decimal
from typing import Dict, Tuple, List, Optional
import schwab
import keychain_manager
import config

class SchwabTrader:
    def __init__(self, client: schwab.client.Client, account_hash: Optional[str] = None):
        self.client = client
        self.account_hash = account_hash or keychain_manager.get_credential(config.KEY_ACCOUNT_HASH)
        
        if not self.account_hash:
            self.account_hash = self._fetch_and_save_account_hash()

    def _fetch_and_save_account_hash(self) -> str:
        """Fetches account hashes from Schwab API and saves the primary account hash to Keychain."""
        resp = self.client.get_account_numbers()
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch account numbers from Schwab API (Status {resp.status_code}): {resp.text}")
        
        accounts = resp.json()
        if not accounts:
            raise ValueError("No brokerage accounts found for this Schwab login.")
        
        # Display available accounts
        print("\n--- SCHWAB ACCOUNTS DISCOVERED ---")
        for idx, acc in enumerate(accounts):
            acc_num = acc.get("accountNumber")
            h_val = acc.get("hashValue")
            print(f"[{idx+1}] Account Number: {acc_num} -> Hash: {h_val}")
        
        # Use first account hash by default
        chosen_hash = accounts[0].get("hashValue")
        keychain_manager.set_credential(config.KEY_ACCOUNT_HASH, chosen_hash)
        print(f"[AUTO-SAVED] Account Hash set to primary account ({accounts[0].get('accountNumber')}) and stored in Keychain!\n")
        return chosen_hash


    def get_account_summary(self) -> Tuple[Decimal, Dict[str, Decimal]]:
        """
        Fetches available cash and current market value of target ETF holdings.
        Returns:
            (available_cash, {ticker: current_dollar_value})
        """
        resp = self.client.get_account(
            self.account_hash,
            fields=schwab.client.Client.Account.Fields.POSITIONS
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch account info from Schwab API (Status {resp.status_code}): {resp.text}")

        account_data = resp.json()
        sec_account = account_data.get("securitiesAccount", {})
        
        # Cash available for trading (handles both CASH and MARGIN account schemas)
        balances = sec_account.get("currentBalances", {})
        cash_raw = (
            balances.get("cashAvailableForTrading")
            if balances.get("cashAvailableForTrading") is not None
            else balances.get("cashBalance", 0)
        )
        cash_available = Decimal(str(cash_raw))

        # Current ETF positions
        positions = sec_account.get("positions", [])
        current_holdings: Dict[str, Decimal] = {t: Decimal("0.00") for t in config.TARGET_PORTFOLIO}

        for pos in positions:
            instrument = pos.get("instrument", {})
            symbol = instrument.get("symbol")
            if symbol in current_holdings:
                market_val = Decimal(str(pos.get("marketValue", 0)))
                current_holdings[symbol] = market_val

        return cash_available, current_holdings

    def get_quotes(self, symbols: List[str]) -> Dict[str, Decimal]:
        """Fetches current ask/last/close price for given ticker symbols."""
        resp = self.client.get_quotes(symbols)
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
        """Builds equity limit buy order spec with GTC duration, SEAMLESS session, and price cap protection."""
        builder = schwab.orders.equities.equity_buy_limit(ticker, shares, str(limit_price.quantize(Decimal("0.01"))))
        if gtc:
            builder.set_duration(schwab.orders.common.Duration.GOOD_TILL_CANCEL)
        builder.set_session(schwab.orders.common.Session.SEAMLESS)
        return builder.build()

    def place_order(self, order_spec: dict) -> bool:
        """Submits order to Schwab API."""
        resp = self.client.place_order(self.account_hash, order_spec)
        if resp.status_code in (200, 201):
            return True
        else:
            raise RuntimeError(f"Order placement failed (Status {resp.status_code}): {resp.text}")

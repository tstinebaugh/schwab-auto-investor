import argparse
import getpass
import sys
from decimal import Decimal
from tabulate import tabulate

import config
import keychain_manager
from rebalancer import calculate_buy_only_rebalance
from auth_manager import get_schwab_client
from trader import SchwabTrader

def handle_setup(args):
    """Interactively setup API credentials in macOS Keychain."""
    print("\n--- Schwab API Credentials Setup (macOS Keychain) ---")
    app_key = input("Enter Schwab App Key (Client ID): ").strip()
    app_secret = getpass.getpass("Enter Schwab App Secret (Client Secret): ").strip()
    account_hash = input("Enter Schwab Account Hash (Press Enter to auto-detect on first login): ").strip()
    callback_url = input(f"Enter Callback URL (Default: {config.DEFAULT_CALLBACK_URL}): ").strip() or config.DEFAULT_CALLBACK_URL

    if not app_key or not app_secret:
        print("[ERROR] App Key and App Secret cannot be empty!")
        sys.exit(1)

    keychain_manager.save_all_credentials(app_key, app_secret, account_hash, callback_url)
    print("\n[SUCCESS] Credentials securely saved to macOS Keychain!")
    if not account_hash:
        print("[NOTE] Account Hash was left blank. It will be automatically fetched & saved on your first run!")
    print("Run 'python main.py status' or 'python main.py rebalance --dry-run' to test authentication.")


def handle_clear(args):
    """Remove stored credentials from Keychain."""
    keychain_manager.delete_credential(config.KEY_APP_KEY)
    keychain_manager.delete_credential(config.KEY_APP_SECRET)
    keychain_manager.delete_credential(config.KEY_ACCOUNT_HASH)
    keychain_manager.delete_credential(config.KEY_CALLBACK_URL)
    print("[SUCCESS] Cleared all Schwab credentials from macOS Keychain.")

def check_vpn_guardrail(args):
    """Enforces US VPN location check by default unless --bypass-vpn is explicitly set."""
    if getattr(args, "bypass_vpn", False):
        print("[WARNING] Skipping US VPN location check (--bypass-vpn active).")
    else:
        is_us, loc_info = config.check_us_vpn()
        if not is_us:
            print(f"[SECURITY ABORT] VPN check failed: Location is not US ({loc_info}). Schwab API request cancelled.")
            sys.exit(1)
        print(f"[SECURITY OK] VPN location verified: {loc_info}")

def handle_status(args):
    """Display detailed account balances, target portfolio holdings, and general account assets."""
    check_vpn_guardrail(args)

    if not keychain_manager.has_credentials():
        print("[ERROR] Credentials missing in Keychain. Please run 'python main.py setup'.")
        sys.exit(1)

    client = get_schwab_client()
    trader = SchwabTrader(client)

    summary = trader.get_account_summary()
    settled_cash = summary["settled_cash"]
    ledger_cash = summary["ledger_cash"]
    buying_power = summary["buying_power"]
    liq_val = summary["liquidation_value"]
    target_positions = summary["target_holdings"]
    all_positions = summary["all_holdings"]

    total_target_val = sum(target_positions.values())

    print("\n=== SCHWAB ACCOUNT BALANCES ===")
    print(f"Settled Cash (Available for API Trading): ${settled_cash:,.2f}")
    print(f"Ledger Cash Balance (cashBalance):        ${ledger_cash:,.2f}")
    print(f"Margin Buying Power:                     ${buying_power:,.2f}")
    print(f"Total Account Liquidation Value:         ${liq_val:,.2f}\n")

    print("=== TARGET PORTFOLIO HOLDINGS ===")
    table_data = []
    for ticker, weight in config.TARGET_PORTFOLIO.items():
        curr_val = target_positions.get(ticker, Decimal("0.00"))
        curr_pct = (curr_val / total_target_val * 100) if total_target_val > 0 else Decimal("0.0")
        target_pct = weight * 100
        table_data.append([
            ticker,
            f"${curr_val:,.2f}",
            f"{curr_pct:.1f}%",
            f"{target_pct:.1f}%"
        ])

    print(tabulate(table_data, headers=["Ticker", "Current Value", "Current %", "Target %"], tablefmt="grid"))

    other_positions = {k: v for k, v in all_positions.items() if k not in config.TARGET_PORTFOLIO}
    if other_positions:
        print("\n=== OTHER ACCOUNT HOLDINGS ===")
        other_table = [[k, f"${v:,.2f}"] for k, v in other_positions.items()]
        print(tabulate(other_table, headers=["Ticker", "Market Value"], tablefmt="grid"))

def handle_rebalance(args):
    """Perform buy-only portfolio rebalancing and execute orders."""
    check_vpn_guardrail(args)

    if not keychain_manager.has_credentials():
        print("[ERROR] Credentials missing in Keychain. Please run 'python main.py setup'.")
        sys.exit(1)

    client = get_schwab_client()
    trader = SchwabTrader(client)

    summary = trader.get_account_summary()

    settled_cash = summary["settled_cash"]
    ledger_cash = summary["ledger_cash"]
    current_positions = summary["target_holdings"]

    if getattr(args, "settled_only", False):
        cash_available = settled_cash
        print(f"\n[INFO] Settled-Only Mode active: Using Settled Cash (${cash_available:,.2f})  (Ledger cashBalance: ${ledger_cash:,.2f})")
    else:
        cash_available = ledger_cash
        print(f"\n[INFO] Cash Available for Rebalancing (cashBalance): ${cash_available:,.2f}  (Settled Cash: ${settled_cash:,.2f})")
        if settled_cash < cash_available:
            print(f"       💡 Note: Using total cashBalance (${cash_available:,.2f}). If Schwab's backend has not finished clearing these funds, orders may be rejected by Schwab API.")

    if cash_available < config.MIN_CASH_THRESHOLD:
        print(f"[SKIP] Available cash for trading (${cash_available:,.2f}) is below minimum threshold (${config.MIN_CASH_THRESHOLD:,.2f}).")
        return

    # Calculate buy-only rebalance allocation
    rebalance_plan = calculate_buy_only_rebalance(current_positions, cash_available, config.TARGET_PORTFOLIO)

    # Fetch real-time quotes to calculate exact share quantities
    print("[INFO] Fetching real-time quotes to compute share quantities...")
    symbols = list(config.TARGET_PORTFOLIO.keys())
    quotes = trader.get_quotes(symbols)

    # 1. Base whole share calculations
    shares_map = {}
    base_cost = Decimal("0.00")
    for ticker, plan in rebalance_plan.items():
        price = quotes.get(ticker, Decimal("0"))
        allocated = plan["allocated_cash"]
        s = int(allocated // price) if price > 0 else 0
        shares_map[ticker] = s
        base_cost += Decimal(str(s)) * price

    # 2. Residual Cash Optimizer: Sweep unspent cash into most underweight affordable ETFs
    remaining_cash = cash_available - base_cost
    total_post_capital = sum(current_positions.get(t, Decimal("0")) for t in config.TARGET_PORTFOLIO) + cash_available

    while True:
        affordable_tickers = [t for t in config.TARGET_PORTFOLIO if quotes.get(t, Decimal("0")) > 0 and quotes[t] <= remaining_cash]
        if not affordable_tickers:
            break

        # Calculate current projected values with allocated shares
        projected_values = {
            t: current_positions.get(t, Decimal("0")) + (Decimal(str(shares_map[t])) * quotes[t])
            for t in config.TARGET_PORTFOLIO
        }
        proj_total = sum(projected_values.values())

        # Select ticker with largest weight shortfall (Target % - Current %)
        best_ticker = None
        max_shortfall = Decimal("-999999")

        for t in affordable_tickers:
            curr_w = (projected_values[t] / proj_total) if proj_total > 0 else Decimal("0")
            shortfall = config.TARGET_PORTFOLIO[t] - curr_w
            if shortfall > max_shortfall:
                max_shortfall = shortfall
                best_ticker = t

        if best_ticker is None:
            break

        shares_map[best_ticker] += 1
        remaining_cash -= quotes[best_ticker]

    table_data = []
    total_alloc = Decimal("0.00")
    order_details = {}
    final_portfolio_val = sum(current_positions.get(t, Decimal("0")) + (Decimal(str(shares_map[t])) * quotes.get(t, Decimal("0"))) for t in config.TARGET_PORTFOLIO)

    for ticker, plan in rebalance_plan.items():
        allocated = plan["allocated_cash"]
        price = quotes.get(ticker, Decimal("0"))
        shares = shares_map[ticker]
        est_cost = Decimal(str(shares)) * price
        total_alloc += est_cost

        curr_pct = f"{plan['current_weight']*100:.1f}%"
        target_pct = f"{plan['target_weight']*100:.1f}%"
        
        post_val = current_positions.get(ticker, Decimal("0")) + est_cost
        post_pct = f"{(post_val / final_portfolio_val * 100):.1f}%" if final_portfolio_val > 0 else "0.0%"
        
        cap_pct = Decimal(str(args.price_cap_pct / 100.0))
        limit_price = (price * (Decimal("1.0") + cap_pct)).quantize(Decimal("0.01")) if price > 0 else Decimal("0")

        order_details[ticker] = {
            "allocated": allocated,
            "price": price,
            "limit_price": limit_price,
            "shares": shares,
            "est_cost": est_cost
        }

        table_data.append([
            ticker,
            f"${plan['current_value']:,.2f}",
            curr_pct,
            target_pct,
            f"${allocated:,.2f}",
            f"${price:,.2f}" if price > 0 else "N/A",
            f"${limit_price:,.2f}" if (args.gtc_limit and price > 0) else "N/A",
            shares,
            f"${est_cost:,.2f}",
            post_pct
        ])

    print("\n=== PROPOSED BUY-ONLY REBALANCE ALLOCATION ===")
    cap_header = f"Limit Cap (+{args.price_cap_pct:g}%)"
    headers = ["Ticker", "Current Val", "Current %", "Target %", "Target ($)", "Price", cap_header, "Shares", "Est Cost", "Post %"] if args.gtc_limit else ["Ticker", "Current Val", "Current %", "Target %", "Target ($)", "Price", "Shares", "Est Cost", "Post %"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print(f"Total Capital to Deploy: ${total_alloc:,.2f}\n")

    market_open, market_reason = config.is_market_open()
    if not market_open and not args.gtc_limit:
        print(f"⚠️ [WARNING] {market_reason}.")
        print("   Day Market orders placed outside regular trading hours (9:35 AM - 4:00 PM ET) are canceled by Schwab.")
        print("   💡 TIP: Add '--gtc-limit' to queue GTC Limit orders (+5% price cap) that automatically fill on the next business day!")

    if args.dry_run:
        print("[DRY-RUN MODE] No orders were placed with Schwab API.")
        return

    if not market_open and not args.gtc_limit:
        print(f"\n[NOTICE] {market_reason}. Please run during continuous trading (9:35 AM - 4:00 PM ET) OR add '--gtc-limit'.")
        return

    order_type_desc = f"GTC LIMIT (Max Cap: +{args.price_cap_pct}%)" if args.gtc_limit else "MARKET BUY"
    confirm = input(f"Are you sure you want to execute these {order_type_desc} orders on Schwab? (type 'YES' to confirm): ").strip()
    if confirm != "YES":
        print("[CANCELLED] Rebalancing cancelled by user.")
        return

    import time
    print("\nExecuting orders on Schwab...")
    orders_placed = 0
    for ticker, details in order_details.items():
        shares = details["shares"]
        if shares <= 0:
            print(f"  [SKIP] {ticker}: Allocated cash (${details['allocated']:,.2f}) is less than 1 share price (${details['price']:,.2f}).")
            continue

        if args.gtc_limit:
            order_spec = trader.build_limit_order_spec(ticker, shares, details["limit_price"], gtc=True)
            log_desc = f"GTC Limit Buy: {shares} share(s) of {ticker} @ Max Limit ${details['limit_price']:,.2f} (~${details['est_cost']:,.2f})"
        else:
            order_spec = trader.build_share_order_spec(ticker, shares)
            log_desc = f"Market Buy: {shares} share(s) of {ticker} (~${details['est_cost']:,.2f})"

        try:
            trader.place_order(order_spec)
            print(f"  [SUCCESS] Submitted {log_desc}")
            orders_placed += 1
        except Exception as e:
            print(f"  [ERROR] Failed to place order for {ticker}: {e}")
            if settled_cash < cash_available:
                print(f"          💡 Hint: Schwab API rejected the order. This typically occurs because Schwab's backend server requires ACH funds to fully settle before allowing API orders.")

        # 1.0s pause to strictly satisfy Schwab's 1-order-per-second API burst governor
        time.sleep(1.0)

    print(f"\n[COMPLETE] Successfully executed {orders_placed} order(s).")

def handle_auth(args):
    """Force re-authentication / token refresh for Schwab API."""
    check_vpn_guardrail(args)

    if not keychain_manager.has_credentials():
        print("[ERROR] Credentials missing in Keychain. Please run 'python main.py setup'.")
        sys.exit(1)

    print("[INFO] Starting Schwab OAuth re-authentication...")
    get_schwab_client(force_reauth=True)


def main():
    parser = argparse.ArgumentParser(description="Schwab Automated Stock Investor & Buy-Only Rebalancer")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # setup
    subparsers.add_parser("setup", help="Save Schwab API credentials to macOS Keychain")

    # clear
    subparsers.add_parser("clear", help="Clear Schwab API credentials from macOS Keychain")

    # auth / reauth
    parser_auth = subparsers.add_parser("auth", aliases=["reauth", "login"], help="Force re-authenticate / refresh Schwab OAuth token")
    parser_auth.add_argument("--bypass-vpn", action="store_true", help="Bypass default US VPN location security check")

    # status
    parser_status = subparsers.add_parser("status", help="Check portfolio holdings and available cash")
    parser_status.add_argument("--bypass-vpn", action="store_true", help="Bypass default US VPN location security check")

    # rebalance
    parser_rebalance = subparsers.add_parser("rebalance", help="Run buy-only rebalancer")
    parser_rebalance.add_argument("--dry-run", action="store_true", help="Simulate rebalance without placing orders")
    parser_rebalance.add_argument("--settled-only", action="store_true", help="Strictly require fully settled cash (settled_cash) instead of total ledger cashBalance")
    parser_rebalance.add_argument("--gtc-limit", action="store_true", help="Place GTC (Good Till Cancel) Limit orders with price cap protection")
    parser_rebalance.add_argument("--price-cap-pct", type=float, default=5.0, help="Price cap percentage limit above current quote price (Default: 5.0%%)")
    parser_rebalance.add_argument("--bypass-vpn", action="store_true", help="Bypass default US VPN location security check")

    args = parser.parse_args()

    if args.command == "setup":
        handle_setup(args)
    elif args.command == "clear":
        handle_clear(args)
    elif args.command in ("auth", "reauth", "login"):
        handle_auth(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "rebalance":
        handle_rebalance(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()


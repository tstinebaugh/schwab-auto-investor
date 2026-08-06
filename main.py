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
    """Display current portfolio status and cash balance."""
    check_vpn_guardrail(args)

    if not keychain_manager.has_credentials():
        print("[ERROR] Credentials missing in Keychain. Please run 'python main.py setup'.")
        sys.exit(1)

    client = get_schwab_client()
    trader = SchwabTrader(client)

    api_cash, current_positions = trader.get_account_summary()
    cash_available = Decimal(str(args.cash)) if args.cash is not None else api_cash
    total_positions_val = sum(current_positions.values())
    total_portfolio_val = total_positions_val + cash_available

    print("\n=== SCHWAB PORTFOLIO SUMMARY ===")
    if args.cash is not None:
        print(f"Available Cash (User Override): ${cash_available:,.2f}  (API Ledger: ${api_cash:,.2f})")
    else:
        print(f"Available Cash (API Ledger):   ${cash_available:,.2f}")
    print(f"Total Target ETFs:             ${total_positions_val:,.2f}")
    print(f"Total Account Value:           ${total_portfolio_val:,.2f}\n")

    table_data = []
    for ticker, weight in config.TARGET_PORTFOLIO.items():
        curr_val = current_positions.get(ticker, Decimal("0.00"))
        curr_pct = (curr_val / total_positions_val * 100) if total_positions_val > 0 else Decimal("0.0")
        target_pct = weight * 100
        table_data.append([
            ticker,
            f"${curr_val:,.2f}",
            f"{curr_pct:.1f}%",
            f"{target_pct:.1f}%"
        ])

    print(tabulate(table_data, headers=["Ticker", "Current Value", "Current %", "Target %"], tablefmt="grid"))

def handle_rebalance(args):
    """Perform buy-only portfolio rebalancing and execute orders."""
    check_vpn_guardrail(args)

    if not keychain_manager.has_credentials():
        print("[ERROR] Credentials missing in Keychain. Please run 'python main.py setup'.")
        sys.exit(1)

    client = get_schwab_client()
    trader = SchwabTrader(client)

    api_cash, current_positions = trader.get_account_summary()
    cash_available = Decimal(str(args.cash)) if args.cash is not None else api_cash
    
    if args.cash is not None:
        print(f"\n[INFO] Cash Available for Trading (User Override): ${cash_available:,.2f}  (API Ledger: ${api_cash:,.2f})")
    else:
        print(f"\n[INFO] Cash Available for Trading (API Ledger): ${cash_available:,.2f}")

    if cash_available < config.MIN_CASH_THRESHOLD:
        print(f"[SKIP] Available cash (${cash_available:,.2f}) is below minimum threshold (${config.MIN_CASH_THRESHOLD:,.2f}). No trades executed.")
        return

    # Calculate buy-only rebalance allocation
    rebalance_plan = calculate_buy_only_rebalance(current_positions, cash_available, config.TARGET_PORTFOLIO)

    # Fetch real-time quotes to calculate exact share quantities
    print("[INFO] Fetching real-time quotes to compute share quantities...")
    symbols = list(config.TARGET_PORTFOLIO.keys())
    quotes = trader.get_quotes(symbols)

    table_data = []
    total_alloc = Decimal("0.00")
    order_details = {}

    for ticker, plan in rebalance_plan.items():
        allocated = plan["allocated_cash"]
        total_alloc += allocated
        curr_pct = f"{plan['current_weight']*100:.1f}%"
        target_pct = f"{plan['target_weight']*100:.1f}%"
        post_pct = f"{plan['post_weight']*100:.1f}%"
        
        price = quotes.get(ticker, Decimal("0"))
        if price > 0:
            shares = int(allocated // price)
        else:
            shares = 0
            
        est_cost = Decimal(str(shares)) * price
        cap_pct = Decimal(str(args.price_cap_pct / 100.0))
        # Use price as base for limit cap (quantized to 2 decimal places)
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

    market_open = config.is_market_open()
    if not market_open and not args.gtc_limit:
        print("⚠️ [WARNING] Regular US Stock Market hours are currently CLOSED (9:30 AM - 4:00 PM Eastern Time).")
        print("   Day Market orders placed outside regular trading hours are immediately canceled by Schwab.")
        print("   💡 TIP: Add '--gtc-limit' to queue GTC Limit orders (+5% price cap) that automatically fill on the next business day!")

    if args.dry_run:
        print("[DRY-RUN MODE] No orders were placed with Schwab API.")
        return

    if not market_open and not args.gtc_limit:
        print("\n[NOTICE] Please run this command during regular market hours (9:30 AM - 4:00 PM ET) OR add '--gtc-limit' to queue GTC orders.")
        return

    order_type_desc = f"GTC LIMIT (Max Cap: +{args.price_cap_pct}%)" if args.gtc_limit else "MARKET BUY"
    confirm = input(f"Are you sure you want to execute these {order_type_desc} orders on Schwab? (type 'YES' to confirm): ").strip()
    if confirm != "YES":
        print("[CANCELLED] Rebalancing cancelled by user.")
        return

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

    print(f"\n[COMPLETE] Successfully executed {orders_placed} order(s).")

def main():
    parser = argparse.ArgumentParser(description="Schwab Automated Stock Investor & Buy-Only Rebalancer")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # setup
    subparsers.add_parser("setup", help="Save Schwab API credentials to macOS Keychain")

    # clear
    subparsers.add_parser("clear", help="Clear Schwab API credentials from macOS Keychain")

    # status
    parser_status = subparsers.add_parser("status", help="Check portfolio holdings and available cash")
    parser_status.add_argument("--cash", type=float, default=None, help="Override available cash amount")
    parser_status.add_argument("--bypass-vpn", action="store_true", help="Bypass default US VPN location security check")

    # rebalance
    parser_rebalance = subparsers.add_parser("rebalance", help="Run buy-only rebalancer")
    parser_rebalance.add_argument("--dry-run", action="store_true", help="Simulate rebalance without placing orders")
    parser_rebalance.add_argument("--cash", type=float, default=None, help="Override available cash amount")
    parser_rebalance.add_argument("--gtc-limit", action="store_true", help="Place GTC (Good Till Cancel) Limit orders with price cap protection")
    parser_rebalance.add_argument("--price-cap-pct", type=float, default=5.0, help="Price cap percentage limit above current quote price (Default: 5.0%%)")
    parser_rebalance.add_argument("--bypass-vpn", action="store_true", help="Bypass default US VPN location security check")

    args = parser.parse_args()

    if args.command == "setup":
        handle_setup(args)
    elif args.command == "clear":
        handle_clear(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "rebalance":
        handle_rebalance(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

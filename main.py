import argparse
import getpass
import sys
import time
from decimal import Decimal
from pathlib import Path

from tabulate import tabulate

import config
import keychain_manager
from auth_manager import InteractiveAuthRequired, get_schwab_client
from rebalancer import allocate_whole_shares, calculate_buy_only_rebalance
from trader import SchwabTrader

# Schwab throttles order placement; space out submissions to stay under the limit.
ORDER_SUBMIT_INTERVAL_SECONDS = 1.0


def handle_setup(args):
    """Interactively store API credentials in the OS keychain."""
    print("\n--- Schwab API Credentials Setup (OS Keychain) ---")
    app_key = input("Enter Schwab App Key (Client ID): ").strip()
    app_secret = getpass.getpass("Enter Schwab App Secret (Client Secret): ").strip()
    account_hash = input("Enter Schwab Account Hash (Press Enter to auto-detect on first login): ").strip()
    callback_url = input(f"Enter Callback URL (Default: {config.DEFAULT_CALLBACK_URL}): ").strip() or config.DEFAULT_CALLBACK_URL

    if not app_key or not app_secret:
        print("[ERROR] App Key and App Secret cannot be empty!")
        sys.exit(1)

    keychain_manager.save_all_credentials(app_key, app_secret, account_hash, callback_url)
    print("\n[SUCCESS] Credentials securely saved to the OS keychain!")
    if not account_hash:
        print("[NOTE] Account Hash was left blank. It will be automatically fetched & saved on your first run!")
    print("Run 'python main.py status' or 'python main.py rebalance --dry-run' to test authentication.")


def handle_clear(args):
    """Remove stored credentials from the OS keychain."""
    keychain_manager.delete_credential(config.KEY_APP_KEY)
    keychain_manager.delete_credential(config.KEY_APP_SECRET)
    keychain_manager.delete_credential(config.KEY_ACCOUNT_HASH)
    keychain_manager.delete_credential(config.KEY_CALLBACK_URL)
    print("[SUCCESS] Cleared all Schwab credentials from the OS keychain.")


def check_vpn_guardrail(args):
    """Enforces a US network-location check by default unless --bypass-vpn is explicitly set."""
    if getattr(args, "bypass_vpn", False):
        print("[WARNING] Skipping US VPN location check (--bypass-vpn active).")
    else:
        is_us, loc_info = config.check_us_vpn()
        if not is_us:
            print(f"[SECURITY ABORT] VPN check failed: Location is not US ({loc_info}). Schwab API request cancelled.")
            sys.exit(1)
        print(f"[SECURITY OK] VPN location verified: {loc_info}")


def require_credentials():
    if not keychain_manager.has_credentials():
        print("[ERROR] Credentials missing in keychain. Please run 'python main.py setup'.")
        sys.exit(1)


def load_target_portfolio(args):
    """Loads the target allocation, exiting with a readable message on bad config."""
    portfolio_path = getattr(args, "portfolio", None)
    if not isinstance(portfolio_path, (str, Path)):
        portfolio_path = None
    try:
        return config.load_portfolio_config(portfolio_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"[CONFIG ERROR] {e}")
        sys.exit(1)


def handle_status(args):
    """Display detailed account balances, target portfolio holdings, and general account assets."""
    check_vpn_guardrail(args)
    require_credentials()
    target_portfolio = load_target_portfolio(args)

    client = get_schwab_client()
    trader = SchwabTrader(client)

    summary = trader.get_account_summary(target_portfolio)
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
    for ticker, weight in target_portfolio.items():
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

    other_positions = {k: v for k, v in all_positions.items() if k not in target_portfolio}
    if other_positions:
        print("\n=== OTHER ACCOUNT HOLDINGS ===")
        other_table = [[k, f"${v:,.2f}"] for k, v in other_positions.items()]
        print(tabulate(other_table, headers=["Ticker", "Market Value"], tablefmt="grid"))


def handle_rebalance(args):
    """Perform buy-only portfolio rebalancing and execute orders."""
    check_vpn_guardrail(args)
    require_credentials()
    target_portfolio = load_target_portfolio(args)

    client = get_schwab_client()
    trader = SchwabTrader(client)

    summary = trader.get_account_summary(target_portfolio)

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
    rebalance_plan = calculate_buy_only_rebalance(current_positions, cash_available, target_portfolio)

    # Fetch real-time quotes to calculate exact share quantities
    print("[INFO] Fetching real-time quotes to compute share quantities...")
    symbols = list(target_portfolio.keys())
    quotes = trader.get_quotes(symbols)
    for ticker in symbols:
        if quotes.get(ticker, Decimal("0")) <= 0:
            print(f"[WARNING] No valid quote returned for {ticker}; it will be skipped this run.")

    shares_map = allocate_whole_shares(rebalance_plan, current_positions, cash_available, quotes, target_portfolio)

    table_data = []
    total_alloc = Decimal("0.00")
    order_details = {}
    final_portfolio_val = sum(
        current_positions.get(t, Decimal("0")) + shares_map[t] * quotes.get(t, Decimal("0"))
        for t in target_portfolio
    )
    cap_pct = Decimal(str(args.price_cap_pct)) / Decimal("100")

    for ticker, plan in rebalance_plan.items():
        allocated = plan["allocated_cash"]
        price = quotes.get(ticker, Decimal("0"))
        shares = shares_map[ticker]
        est_cost = shares * price
        total_alloc += est_cost

        curr_pct = f"{plan['current_weight']*100:.1f}%"
        target_pct = f"{plan['target_weight']*100:.1f}%"

        post_val = current_positions.get(ticker, Decimal("0")) + est_cost
        post_pct = f"{(post_val / final_portfolio_val * 100):.1f}%" if final_portfolio_val > 0 else "0.0%"

        limit_price = (price * (Decimal("1.0") + cap_pct)).quantize(Decimal("0.01")) if price > 0 else Decimal("0")

        order_details[ticker] = {
            "allocated": allocated,
            "price": price,
            "limit_price": limit_price,
            "shares": shares,
            "est_cost": est_cost
        }

        row = [
            ticker,
            f"${plan['current_value']:,.2f}",
            curr_pct,
            target_pct,
            f"${allocated:,.2f}",
            f"${price:,.2f}" if price > 0 else "N/A",
        ]
        if args.gtc_limit:
            row.append(f"${limit_price:,.2f}" if price > 0 else "N/A")
        row += [shares, f"${est_cost:,.2f}", post_pct]
        table_data.append(row)

    print("\n=== PROPOSED BUY-ONLY REBALANCE ALLOCATION ===")
    headers = ["Ticker", "Current Val", "Current %", "Target %", "Target ($)", "Price"]
    if args.gtc_limit:
        headers.append(f"Limit Cap (+{args.price_cap_pct:g}%)")
    headers += ["Shares", "Est Cost", "Post %"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print(f"Total Capital to Deploy: ${total_alloc:,.2f}\n")

    market_open, market_reason = config.is_market_open()
    if not market_open and not args.gtc_limit:
        print(f"⚠️ [WARNING] {market_reason}.")
        print("   Day Market orders placed outside regular trading hours (9:30 AM - 4:00 PM ET) are canceled by Schwab.")
        print(f"   💡 TIP: Add '--gtc-limit' to queue GTC Limit orders (+{args.price_cap_pct:g}% price cap) that automatically fill on the next business day!")

    if args.dry_run:
        print("[DRY-RUN MODE] No orders were placed with Schwab API.")
        return

    if not market_open and not args.gtc_limit:
        print(f"\n[NOTICE] {market_reason}. Please run during continuous trading (9:30 AM - 4:00 PM ET) OR add '--gtc-limit'.")
        return

    order_type_desc = f"GTC LIMIT (Max Cap: +{args.price_cap_pct:g}%)" if args.gtc_limit else "MARKET BUY"
    if getattr(args, "yes", False) is True:
        print(f"[INFO] --yes supplied: executing {order_type_desc} orders without an interactive prompt.")
    elif not sys.stdin.isatty():
        print("[ABORT] Refusing to place live orders without a terminal to confirm. Re-run with '--yes' for unattended runs.")
        sys.exit(1)
    else:
        confirm = input(f"Are you sure you want to execute these {order_type_desc} orders on Schwab? (type 'YES' to confirm): ").strip()
        if confirm != "YES":
            print("[CANCELLED] Rebalancing cancelled by user.")
            return

    print("\nExecuting orders on Schwab...")
    orders_placed = 0
    orders_failed = 0
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
            orders_failed += 1
            print(f"  [ERROR] Failed to place order for {ticker}: {e}")
            if settled_cash < cash_available:
                print("          💡 Hint: Schwab API rejected the order. This typically occurs because Schwab requires ACH funds to fully settle before allowing API orders.")
            print("          💡 Note: If orders are placed but auto-canceled on Schwab, ensure you have accepted the thinkorswim (TOS) Terms of Service on the Schwab website.")

        time.sleep(ORDER_SUBMIT_INTERVAL_SECONDS)

    print(f"\n[COMPLETE] Submitted {orders_placed} order(s); {orders_failed} failed.")
    if orders_failed:
        sys.exit(1)


def handle_auth(args):
    """Force re-authentication / token refresh for Schwab API."""
    check_vpn_guardrail(args)
    require_credentials()

    print("[INFO] Starting Schwab OAuth re-authentication...")
    get_schwab_client(force_reauth=True)


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Schwab Automated Stock Investor & Buy-Only Rebalancer")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("setup", help="Save Schwab API credentials to the OS keychain")
    subparsers.add_parser("clear", help="Clear Schwab API credentials from the OS keychain")

    parser_auth = subparsers.add_parser("auth", aliases=["reauth", "login"], help="Force re-authenticate / refresh Schwab OAuth token")
    parser_auth.add_argument("--bypass-vpn", action="store_true", help="Bypass default US VPN location security check")

    parser_status = subparsers.add_parser("status", help="Check portfolio holdings and available cash")
    parser_status.add_argument("--portfolio", type=str, default=None, help="Path to custom portfolio targets JSON file (Default: portfolio.json)")
    parser_status.add_argument("--bypass-vpn", action="store_true", help="Bypass default US VPN location security check")

    parser_rebalance = subparsers.add_parser("rebalance", help="Run buy-only rebalancer")
    parser_rebalance.add_argument("--portfolio", type=str, default=None, help="Path to custom portfolio targets JSON file (Default: portfolio.json)")
    parser_rebalance.add_argument("--dry-run", action="store_true", help="Simulate rebalance without placing orders")
    parser_rebalance.add_argument("--settled-only", action="store_true", help="Strictly require fully settled cash (settled_cash) instead of total ledger cashBalance")
    parser_rebalance.add_argument("--gtc-limit", action="store_true", help="Place GTC (Good Till Cancel) Limit orders with price cap protection")
    parser_rebalance.add_argument("--price-cap-pct", type=positive_float, default=5.0, help="Price cap percentage limit above current quote price (Default: 5.0%%)")
    parser_rebalance.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt (for scheduled/unattended runs)")
    parser_rebalance.add_argument("--bypass-vpn", action="store_true", help="Bypass default US VPN location security check")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "setup": handle_setup,
        "clear": handle_clear,
        "auth": handle_auth,
        "reauth": handle_auth,
        "login": handle_auth,
        "status": handle_status,
        "rebalance": handle_rebalance,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return

    try:
        handler(args)
    except InteractiveAuthRequired as e:
        print(f"[AUTH REQUIRED] {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n[CANCELLED] Interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()

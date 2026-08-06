# Schwab Automated Stock Investor & Buy-Only Rebalancer

An automated monthly investment tool powered by the **Charles Schwab Trader API** and **`schwab-py`**. It invests available account cash according to your target ETF allocation using **buy-only dynamic rebalancing** (never sells existing shares), storing all API keys securely in the **macOS Keychain**.

---

## Target Portfolio Allocation

| Ticker | Asset Class / Fund Name | Target Weight |
| :--- | :--- | :--- |
| **AVLV** | Avantis U.S. Large Cap Value ETF | **45%** |
| **DFAI** | Dimensional U.S. Core Equity 2 ETF | **25%** |
| **AVUV** | Avantis U.S. Small Cap Value ETF | **15%** |
| **AVDV** | Avantis International Small Cap Value ETF | **10%** |
| **DFEM** | Dimensional Emerging Markets Core Equity 2 ETF | **5%** |

---

## TL;DR: Schwab Developer App Setup & Callback URL

When creating your application on the [Schwab Developer Portal](https://developer.schwab.com):

1. **Callback URL / Redirect URI**: Use **`https://127.0.0.1`** (or `https://127.0.0.1:8080/callback`).
   - *Why HTTPS for local?* Schwab's API enforcement requires `https://` even for local redirect endpoints.
   - *How login works:* On first run, the script opens a browser for Schwab login. After approving, Schwab redirects your browser to `https://127.0.0.1/?code=...`. The browser page will say *"Can't connect to server"*—this is expected! Simply **copy the entire redirected URL** from your browser address bar and paste it back into the terminal prompt.
2. **App Key & App Secret**: Obtained from your approved Schwab Developer App dashboard.
3. **Account Hash**: Obtained from Schwab API or printed during first login status check.

---

## Keyring / Keychain Setup Directions

### Option A: Interactive Script Command (Recommended)
Run the built-in setup helper to securely prompt and write credentials to macOS Keychain:
```bash
.venv/bin/python main.py setup
```
You will be prompted for:
- App Key (Client ID)
- App Secret (Client Secret)
- Account Hash (**Press Enter to skip**—the script will automatically fetch and save your account hash on your first run!)
- Callback URL (press Enter for default `https://127.0.0.1`)


### Option B: Direct macOS Terminal `security` Commands
If you prefer saving credentials directly via the macOS terminal:
```bash
security add-generic-password -a "$USER" -s "schwab_investor_app_key" -w "YOUR_APP_KEY" -U
security add-generic-password -a "$USER" -s "schwab_investor_app_secret" -w "YOUR_APP_SECRET" -U
security add-generic-password -a "$USER" -s "schwab_investor_account_hash" -w "YOUR_ACCOUNT_HASH" -U
security add-generic-password -a "$USER" -s "schwab_investor_callback_url" -w "https://127.0.0.1" -U
```

---

## Installation & Usage

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Unit Tests**:
   ```bash
   python3 -m unittest tests/test_rebalancer.py
   ```

3. **Check Portfolio Status**:
   ```bash
   .venv/bin/python main.py status
   ```

4. **Run Rebalance Simulation (Dry-Run)**:
   ```bash
   .venv/bin/python main.py rebalance --dry-run
   ```

5. **Execute Live Monthly Investment**:
   - *During regular market hours (9:30 AM - 4:00 PM ET)*:
     ```bash
     .venv/bin/python main.py rebalance
     ```
   - *Outside market hours (GTC Limit + 3% Price Cap Collar)*:
     ```bash
     .venv/bin/python main.py rebalance --gtc-limit --price-cap-pct 3.0
     ```

*Note: The script verifies your US VPN location automatically on every run. If you ever need to bypass the VPN check, pass `--bypass-vpn`.*

---

## Monthly Automation (macOS Cron)

To automatically invest cash on the 1st of every month at 10:00 AM (during market hours):

1. Open your crontab editor:
   ```bash
   crontab -e
   ```
2. Add the following line (update path to your python environment and project directory):
   ```cron
   0 10 1 * * cd /Users/travisstinebaugh/schwab-investor && /usr/bin/python3 main.py rebalance >> /Users/travisstinebaugh/schwab-investor/rebalance.log 2>&1
   ```

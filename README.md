# Schwab Automated Stock Investor & Buy-Only Rebalancer

An automated monthly investment tool powered by the **Charles Schwab Trader API** and **`schwab-py`**. It invests available account cash according to your target ETF allocation using **buy-only dynamic rebalancing** (never sells existing shares), storing all API keys securely in the **macOS Keychain**.

---

## Target Portfolio Allocation & Factor Tilt Rationale

The default portfolio is inspired by **Ben Felix's (PWL Capital / Rational Reminder) evidence-based multi-factor investing framework**, systematically tilting toward independent risk dimensions to capture higher expected risk-adjusted returns over long horizons.

### Default Portfolio Target Weights

| Ticker | Asset Class / Fund Name | Target Weight | Factor Exposures |
| :--- | :--- | :---: | :--- |
| **AVLV** | Avantis U.S. Large Cap Value ETF | **45%** | Market, Value, High Profitability |
| **DFAI** | Dimensional U.S. Core Equity 2 ETF | **25%** | Market, Integrated Multi-Factor (Size, Value, Profitability) |
| **AVUV** | Avantis U.S. Small Cap Value ETF | **15%** | Size (Small-Cap), Value, High Profitability |
| **AVDV** | Avantis International Small Cap Value ETF | **10%** | International Developed, Size, Value, Profitability |
| **DFEM** | Dimensional Emerging Markets Core Equity 2 ETF | **5%** | Emerging Markets Equity, Systematic Factor Tilts |

---

### Investment Philosophy: Why Factor Tilting?

Traditional passive index investing relies on the **Capital Asset Pricing Model (CAPM)**, assuming that market risk (Beta) is the sole driver of equity returns. However, over five decades of empirical asset pricing research—pioneered by Nobel laureates **Eugene Fama** and **Kenneth French**—has proven that differences in expected returns are explained by multiple independent risk factors:

1. **Size (Small Minus Big - SmB)**: Smaller market-cap companies have historically delivered a return premium over large caps due to unique fundamental risks.
2. **Value (High Minus Low - HmL)**: Inexpensive companies relative to book value, cash flows, and enterprise value carry higher expected returns than high-multiple growth stocks.
3. **Profitability (Robust Minus Weak - RmW)**: Companies with high operating profitability systematically outperform those with weak profitability for a given level of valuation.
4. **Investment (Conservative Minus Aggressive - CmA)**: Firms that invest capital conservatively outperform aggressive capex firms that dilute shareholder equity.

By combining broad market core equity with systematic tilts toward small-cap, value, and robust profitability, investors can achieve **multi-dimensional factor diversification**—improving expected long-term risk-adjusted returns without relying on subjective stock picking or market timing.

---

### Why Avantis Investors & Dimensional Fund Advisors (DFA)?

Traditional cap-weighted factor index funds (such as standard Russell 2000 or S&P 600 Value index funds) suffer from significant structural flaws:
- **Rigid Annual Reconstitution**: Predictable annual index rebalancing leads to predatory front-running by hedge funds and excessive transaction costs.
- **Unprofitable "Lottery" Stocks**: Naive small-cap indices are loaded with cash-burning, low-profitability companies that historically drag down small-cap performance.
- **Negative Momentum Drag**: Mechanical index funds often buy falling knives right into downward momentum.

**Avantis and Dimensional solve these issues through dynamic, daily-managed rules-based execution:**
- **Daily Active Implementation**: Rather than rigid annual turnover, they trade continuously at low turnover, patient execution, and favorable spreads.
- **Integrated Profitability & Investment Filters**: They eliminate low-profitability/high-reinvestment junk stocks from the investable universe.
- **Momentum Friction Screens**: They delay buys on stocks with negative short-term momentum and delay sells on stocks with positive short-term momentum.

#### Asset Allocation Breakdown:
- **AVLV (45%)**: Acts as the cornerstone US equity anchor, providing lower-volatility US large-cap value with high profitability screening.
- **DFAI (25%)**: Delivers broad US core market coverage with integrated factor tilts (tilted slightly toward smaller, cheaper, and higher-profitability firms across the entire US market).
- **AVUV (15%)**: The powerhouse factor engine, targeting the intersection of deep small size, low valuation multiples, and robust cash profitability.
- **AVDV (10%)**: Extends the small-cap value premium to developed international markets (Europe, Japan, Australasia) for global factor diversification.
- **DFEM (5%)**: Captures emerging market equity risk premiums with systematic multi-factor weighting and country-level risk controls.

---

## Customizing Your Target Portfolio (`portfolio.json`)

You can easily modify your target allocations or swap tickers by editing **`portfolio.json`** in the project root:

```json
{
  "AVLV": 45,
  "DFAI": 25,
  "AVUV": 15,
  "AVDV": 10,
  "DFEM": 5
}
```

### Supported Formats & Validation
- **Percentages or Decimals**: Specify weights as whole percentages (`45`, `45.0`, `"45%"`) or decimal fractions (`0.45`).
- **Strict 100% Sum Check**: The script automatically validates that total target weights sum to exactly **100%** (or **1.0**).
- **Valid Tickers**: Tickers must be valid exchange symbols (e.g. `AVLV`, `BRK.B`, `VTI`).
- **Custom Profile Flag**: You can maintain multiple portfolio configurations (e.g. for different accounts or goals) and pass them via the `--portfolio` argument:
  ```bash
  .venv/bin/python main.py status --portfolio my_custom_portfolio.json
  .venv/bin/python main.py rebalance --portfolio my_custom_portfolio.json
  ```

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
   python3 -m unittest discover -s tests
   ```

3. **Check Portfolio Status**:
   ```bash
   .venv/bin/python main.py status
   # Or with a custom portfolio configuration:
   .venv/bin/python main.py status --portfolio portfolio.json
   ```

4. **Re-Authenticate / Refresh Schwab OAuth Token**:
   ```bash
   .venv/bin/python main.py auth
   ```
   *Note: If the script encounters an authentication error or an expired token during any operation (`status`, `rebalance`), it will automatically prompt you to re-authenticate.*

5. **Run Rebalance Simulation (Dry-Run)**:
   ```bash
   .venv/bin/python main.py rebalance --dry-run
   # Or with a custom portfolio configuration:
   .venv/bin/python main.py rebalance --portfolio portfolio.json --dry-run
   ```

6. **Execute Live Monthly Investment**:
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
   0 10 1 * * cd /path/to/schwab-investor && /path/to/schwab-investor/.venv/bin/python main.py rebalance >> /path/to/schwab-investor/rebalance.log 2>&1
   ```

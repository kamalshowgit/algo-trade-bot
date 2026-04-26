import yfinance as yf
import pandas as pd
import numpy as np
import random
from engine import calculate_signals

# ==============================
# CONFIG
# ==============================
INITIAL_CAPITAL = 100000
LOT_SIZE = 50
BROKERAGE = 60
SLIPPAGE_BPS = 0.0002
MAX_DAILY_LOSS = 0.05
COOLDOWN_BARS = 10

SYMBOL = "^NSEI"


# ==============================
# DATA FETCH (ROBUST)
# ==============================
def fetch_data():
    import yfinance as yf
    import pandas as pd

    print("Fetching data...")

    # -------------------------------
    # Try intraday first (15m)
    # -------------------------------
    df = yf.download("^NSEI", period="60d", interval="15m", progress=False)

    if not df.empty:
        print("✅ Using 15m data (last 60 days)")
    else:
        print("⚠️ 15m failed → switching to daily (2y)")
        df = yf.download("^NSEI", period="2y", interval="1d", progress=False)

    if df.empty:
        raise ValueError("❌ No data fetched from yfinance")

    # -------------------------------
    # Fix multi-index columns (IMPORTANT)
    # -------------------------------
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()

    # -------------------------------
    # Normalize Datetime column
    # -------------------------------
    if "Datetime" not in df.columns:
        if "Date" in df.columns:
            df.rename(columns={"Date": "Datetime"}, inplace=True)
        else:
            raise ValueError("❌ No Datetime column found")

    df["Datetime"] = pd.to_datetime(df["Datetime"])

    # -------------------------------
    # Normalize OHLCV columns
    # -------------------------------
    column_map = {}

    for col in df.columns:
        lc = col.lower()

        if lc == "open":
            column_map[col] = "Open"
        elif lc == "high":
            column_map[col] = "High"
        elif lc == "low":
            column_map[col] = "Low"
        elif lc == "close":
            column_map[col] = "Close"
        elif lc == "adj close":
            column_map[col] = "Close"
        elif lc == "volume":
            column_map[col] = "Volume"

    df = df.rename(columns=column_map)

    # -------------------------------
    # Ensure ALL required columns exist
    # -------------------------------
    required_cols = ["Open", "High", "Low", "Close", "Volume"]

    for col in required_cols:
        if col not in df.columns:
            print(f"⚠️ Missing {col} → filling with default")
            df[col] = 0.0

    # Convert to numeric
    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop bad rows
    df = df.dropna(subset=["Close"])

    # Final selection
    df = df[["Datetime", "Open", "High", "Low", "Close", "Volume"]]

    # -------------------------------
    # Convert to records
    # -------------------------------
    records = df.to_dict("records")

    # Debug sample
    print("Sample record:", records[0])
    print("Data points:", len(records))

    return records


# ==============================
# SLIPPAGE
# ==============================
def apply_slippage(price, side):
    slip = SLIPPAGE_BPS * (1 + random.uniform(-0.5, 0.5))
    return price * (1 + slip if side == "BUY" else 1 - slip)


# ==============================
# BACKTEST ENGINE
# ==============================
def backtest(records):

    capital = INITIAL_CAPITAL
    equity_curve = []
    trades = []

    in_position = False
    pos_type = None
    entry_price = 0
    qty = 0
    stop_loss = None
    target_price = None

    last_trade_bar = -COOLDOWN_BARS
    daily_pnl = 0
    current_day = None

    for i in range(60, len(records)):

        row = records[i]
        price = float(row["Close"])
        time = row["Datetime"]

        # Reset daily PnL
        if current_day != time.date():
            current_day = time.date()
            daily_pnl = 0

        # Daily loss protection
        if daily_pnl <= -MAX_DAILY_LOSS * INITIAL_CAPITAL:
            equity_curve.append(capital)
            continue

        # Cooldown
        if i - last_trade_bar < COOLDOWN_BARS:
            equity_curve.append(capital)
            continue

        recent_records = records[i-60:i+1]
        candles_df = pd.DataFrame(recent_records)
        window = candles_df["Close"].tolist()

        signal = calculate_signals(
            price_list=window,
            current_time=time,
            position=(1 if pos_type == "LONG" else -1) if in_position else 0,
            entry_price=entry_price,
            candles_df=candles_df,
            capital=capital,
            lot_size=LOT_SIZE
        )

        action = signal.get("action", "WAIT")

        # DEBUG (every 200 steps)
        if i % 200 == 0:
            print(f"{time} | Action: {action}")

        # ================= ENTRY =================
        if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:

            entry_price = apply_slippage(price, "BUY" if action == "BUY_LONG" else "SELL")

            stop_loss = entry_price * (
                (1 - signal["stop_loss_pct"]) if action == "BUY_LONG"
                else (1 + signal["stop_loss_pct"])
            )
            target_price = entry_price * (
                (1 + signal["target_pct"]) if action == "BUY_LONG"
                else (1 - signal["target_pct"])
            )

            qty = int(signal.get("suggested_qty", LOT_SIZE))

            pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
            in_position = True
            last_trade_bar = i

        # ================= POSITION MANAGEMENT =================
        elif in_position:

            pnl_pct = ((price - entry_price) / entry_price) if pos_type == "LONG" else ((entry_price - price) / entry_price)

            # Trailing logic
            if pnl_pct >= signal["breakeven_pct"]:
                if pos_type == "LONG":
                    stop_loss = max(stop_loss, entry_price)
                    stop_loss = max(stop_loss, price * (1 - signal["trail_distance"]))
                else:
                    stop_loss = min(stop_loss, entry_price)
                    stop_loss = min(stop_loss, price * (1 + signal["trail_distance"]))

            exit_flag = False

            # Stop loss
            if (pos_type == "LONG" and price <= stop_loss) or (pos_type == "SHORT" and price >= stop_loss):
                exit_flag = True
                
            # Target profit hit
            elif (pos_type == "LONG" and price >= target_price) or (pos_type == "SHORT" and price <= target_price):
                exit_flag = True

            # Signal exit
            elif action.startswith("EXIT"):
                exit_flag = True

            # EOD exit
            elif hasattr(time, "hour") and time.hour == 15 and time.minute >= 15:
                exit_flag = True

            if exit_flag:
                exit_price = apply_slippage(price, "SELL" if pos_type == "LONG" else "BUY")

                pnl_points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                net = pnl_points * qty - BROKERAGE

                capital += net
                daily_pnl += net
                trades.append(net)

                in_position = False
                pos_type = None
                entry_price = 0
                qty = 0
                stop_loss = None
                target_price = None

        equity_curve.append(capital)

    return trades, equity_curve


# ==============================
# REPORT
# ==============================
def generate_report(trades, equity_curve):

    if not equity_curve:
        print("❌ No equity data generated")
        return

    total = sum(trades)
    num_trades = len(trades)

    win_rate = (sum(1 for t in trades if t > 0) / num_trades * 100) if num_trades else 0
    avg_trade = total / num_trades if num_trades else 0

    peak = equity_curve[0]
    max_dd = 0

    for val in equity_curve:
        peak = max(peak, val)
        dd = (peak - val) / peak
        max_dd = max(max_dd, dd)

    print("\n===== BACKTEST REPORT =====")
    print("Trades:", num_trades)
    print("Total PnL:", round(total, 2))
    print("Win Rate:", round(win_rate, 2), "%")
    print("Avg Trade:", round(avg_trade, 2))
    print("Max Drawdown:", round(max_dd * 100, 2), "%")
    print("Final Capital:", round(equity_curve[-1], 2))


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":

    records = fetch_data()

    print("Running backtest...")
    trades, equity = backtest(records)

    print("Total trades:", len(trades))

    generate_report(trades, equity)
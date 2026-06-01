import pandas as pd # Import pandas for data manipulation and tabular data
import numpy as np # Import numpy for array calculations
import yfinance as yf # Import yfinance for downloading historical stock data
import os # Import os to interact with environment variables and file paths
import time # Import time for sleeping/pausing execution
import glob # Import glob to search for files matching a specific pattern
from dataclasses import dataclass # Import dataclass for structured objects (fixed syntax typo datac3lass -> dataclass)
from datetime import datetime, timedelta, time as dt_time # Import datetime tools for timestamp management
from engine import STRATEGIES, MIN_SIGNAL_CANDLES, calculate_signals, risk_management # Import core trading logic from engine.py
from dotenv import load_dotenv # Import load_dotenv to read secrets from a .env file

load_dotenv() # Execute load_dotenv to load environment variables into the os.environ dictionary

def get_int_env(name, default, minimum=None): # Utility function to fetch int ENV variables safely
    try: # Begin try-catch block for parsing
        value = int(os.getenv(name, str(default))) # Pull OS environment variable and cast to integer
    except (TypeError, ValueError): # If the variable doesn't parse to an integer
        value = default # Revert to the fallback integer
    if minimum is not None: # If a lower bound is requested
        value = max(minimum, value) # Apply the minimum bound dynamically
    return value # Output the sanitized integer


def get_bool_env(name, default): # Utility function to fetch boolean ENV variables safely
    return os.getenv(name, str(default)).strip().lower() == "true" # Returns exact True if environment string matches "true", else False


CONFIG = { # Master configuration dictionary loading global execution parameters
    "SYMBOL": "^NSEI", # The default backtesting index symbol
    "LOT_SIZE": 65, # Standard lot sizing for NIFTY
    "CAPITAL": 100000, # Base theoretical capital pool
    "SLIPPAGE_BPS": 0.0003, # Standard internal slippage representation (0.03%)
    "OUTPUT_FILE": "angel_backtest_results.csv", # Destination file for standard runs
    "PAPER_OUTPUT_FILE": os.getenv("PAPER_OUTPUT_FILE", "paper_trade_history.csv"), # Destination for paper runs
    "PRICE_HISTORY_FILE": os.getenv("PRICE_HISTORY_FILE", "price_history.csv"), # Continuous price logging output file
    "LIVE_MODE": get_bool_env("LIVE_MODE", False), # Defines if the app executes Real trades
    "PAPER_MODE": get_bool_env("PAPER_MODE", True), # Defines if the app executes Paper trades
    "MARKET_DATA_EXCHANGE": os.getenv("MARKET_DATA_EXCHANGE", "NSE"), # Defines API connection exchange string
    "MARKET_DATA_SYMBOL": os.getenv("MARKET_DATA_SYMBOL", "NIFTY"), # Defines API forward charting symbol
    "MARKET_DATA_SYMBOL_TOKEN": os.getenv("MARKET_DATA_SYMBOL_TOKEN", "99926000"), # Defines API Token Key
    "MARKET_DATA_INTERVAL": os.getenv("MARKET_DATA_INTERVAL", "FIVE_MINUTE"), # API Polling interval size
    "MARKET_POLL_SECONDS": get_int_env("MARKET_POLL_SECONDS", 30, minimum=5), # Latency spacing for loops
    "CANDLE_LOOKBACK_DAYS": get_int_env("CANDLE_LOOKBACK_DAYS", 2, minimum=1),
    "TRADE_EXCHANGE": os.getenv("TRADE_EXCHANGE", "NSE"),
    "TRADE_SYMBOL": os.getenv("TRADE_SYMBOL", "NIFTY30APR26FUT"),
    "TRADE_SYMBOL_TOKEN": os.getenv("TRADE_SYMBOL_TOKEN", "99926000"),
    "FORWARD_STRATEGY": os.getenv("FORWARD_STRATEGY", "strategy_1").strip().lower(),
    "AUTO_TUNE_FROM_LOCAL_DATA": get_bool_env("AUTO_TUNE_FROM_LOCAL_DATA", True),
    "MIN_LOCAL_TRAINING_FILES": get_int_env("MIN_LOCAL_TRAINING_FILES", 3, minimum=1),
    "LOCAL_PRICE_HISTORY_PATTERNS": os.getenv("LOCAL_PRICE_HISTORY_PATTERNS", "../price_history*.csv,price_history*.csv"),
    "MAX_LATENCY_SECONDS": get_int_env("MAX_LATENCY_SECONDS", 2),
}

# Angel One credentials
API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")
EMPTY_TRADE_COLUMNS = [
    "Trade_ID",
    "Entry_Time",
    "Exit_Time",
    "Type",
    "Qty",
    "Entry_Price",
    "Exit_Price",
    "Points",
    "Net_PnL",
    "Exit_Reason",
    "Entry_RSI",
    "Entry_EMA_F",
    "Exit_RSI",
    "Entry_Score",
    "Strategy",
    "Planned_Risk",
    "Daily_PnL_After",
    "Risk_Allowed",
    "Session_Stop",
]
PRICE_HISTORY_COLUMNS = [
    "DateTime",
    "Price",
    "High",
    "Low",
    "Volume",
    "Signal",
    "RSI",
    "RSI_FAST",
    "EMA_FAST",
    "SLOPE",
    "PERCENT_B",
    "ATR",
    "Volume_Ratio",
    "Entry_Score",
    "REGIME",
    "Strategy",
    "Stop_Loss",
    "Target",
]


def get_forward_strategy_name():
    strategy_name = CONFIG["FORWARD_STRATEGY"]
    if strategy_name not in STRATEGIES:
        print(f"⚠️  Unknown FORWARD_STRATEGY '{strategy_name}'. Falling back to strategy_1.")
        return "strategy_1"
    return strategy_name


def minute_to_label(total_minutes): # Helper: Convert total minutes into an HH:MM string
    hours = total_minutes // 60 # Extract the hours
    minutes = total_minutes % 60 # Extract the remaining minutes
    return f"{hours:02d}:{minutes:02d}" # Format correctly


@dataclass(frozen=True) # Used to create immutable, structured config profiles
class TradingProfile: # Contains the active trading logic configuration state
    strategy_name: str # The strategy ID from STRATEGIES
    entry_start_minute: int = 555 # 9:15 AM default start
    entry_end_minute: int = 915 # 3:15 PM default stop
    skip_midday: bool = False # Parameter to optionally avoid sideways lunch chops
    allow_long: bool = True # Parameter to allow bullish calls
    allow_short: bool = True # Parameter to allow bearish calls
    source: str = "config" # String metadata to identify logic origin

    def permits_entry(self, action, current_time): # Validates whether a time-action is within profile constraints
        minute = current_time.hour * 60 + current_time.minute # Convert current timestamp to raw daily minutes
        if minute < self.entry_start_minute or minute > self.entry_end_minute: # Ensure it is inside the trading window boundaries
            return False # Reject entry condition
        if self.skip_midday and 735 <= minute <= 795: # Block 12:15 to 1:15pm logic
            return False # Reject entry condition
        if action == "BUY_LONG": # Validate bullish rules
            return self.allow_long # Use boolean
        if action == "SELL_SHORT": # Validate bearish rules
            return self.allow_short # Use boolean
        return True # Accepted

    def describe(self):
        direction = "both sides"
        if self.allow_long and not self.allow_short:
            direction = "long only"
        elif self.allow_short and not self.allow_long:
            direction = "short only"
        midday = "skip 12:15-13:15" if self.skip_midday else "trade through lunch"
        return (
            f"{self.strategy_name} | {minute_to_label(self.entry_start_minute)}-"
            f"{minute_to_label(self.entry_end_minute)} | {direction} | {midday}"
        )


def build_default_trading_profile():
    return TradingProfile(strategy_name=get_forward_strategy_name(), source="config")


def find_local_price_history_files():
    matched_paths = []
    for raw_pattern in CONFIG["LOCAL_PRICE_HISTORY_PATTERNS"].split(","):
        pattern = raw_pattern.strip()
        if not pattern:
            continue
        matched_paths.extend(glob.glob(pattern))
    unique_paths = []
    seen = set()
    for path in sorted(matched_paths):
        normalized = os.path.abspath(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(path)
    return unique_paths


def load_local_price_history_records():
    records_by_day = []
    used_files = []

    for path in find_local_price_history_files():
        try:
            df = pd.read_csv(path)
        except Exception:
            continue

        if df.empty or "DateTime" not in df.columns or "Price" not in df.columns:
            continue

        day_records = []
        for _, row in df.iterrows():
            price = row.get("Price")
            timestamp = row.get("DateTime")
            if pd.isna(price) or pd.isna(timestamp):
                continue
            try:
                close_price = float(price)
                day_records.append({
                    "DateTime": normalize_market_timestamp(timestamp).to_pydatetime(),
                    "Open": close_price,
                    "High": float(row.get("High", close_price) or close_price),
                    "Low": float(row.get("Low", close_price) or close_price),
                    "Close": close_price,
                    "Volume": float(row.get("Volume", 0.0) or 0.0),
                })
            except Exception:
                continue

        if len(day_records) < 26:
            continue

        records_by_day.append(day_records)
        used_files.append(path)

    return records_by_day, used_files


def precompute_strategy_signals(records_by_day, strategy_names):
    signal_cache = {}

    for strategy_name in strategy_names:
        day_cache = []
        for day_records in records_by_day:
            candle_cache = []
            for index in range(MIN_SIGNAL_CANDLES - 1, len(day_records)):
                record = day_records[index]
                recent_candles = build_candles_frame_from_records(day_records[max(0, index - 59):index + 1])
                price_window = recent_candles["Close"].tolist()
                signal_data = calculate_signals(
                    price_list=price_window,
                    current_time=record["DateTime"],
                    position=0,
                    entry_price=0.0,
                    strategy_name=strategy_name,
                    candles_df=recent_candles,
                    capital=CONFIG["CAPITAL"],
                    lot_size=CONFIG["LOT_SIZE"],
                )
                candle_cache.append({
                    "DateTime": record["DateTime"],
                    "Close": float(record["Close"]),
                    "SignalData": signal_data,
                })
            day_cache.append(candle_cache)
        signal_cache[strategy_name] = day_cache

    return signal_cache


def simulate_profile_from_cache(profile, signal_cache):
    pnls = []

    for candles in signal_cache.get(profile.strategy_name, []):
        in_position = False
        pos_type = ""
        entry_price = 0.0
        quantity = 0
        stop_loss_price = None
        target_price = None
        entry_data = {}
        daily_pnl = 0.0
        peak_daily_pnl = 0.0
        daily_trading_paused = False
        pause_reason = ""

        for candle in candles:
            current_time = candle["DateTime"]
            current_price = candle["Close"]
            signal_data = candle["SignalData"]
            action = signal_data.get("action", "WAIT")
            params = risk_management()

            peak_daily_pnl = max(peak_daily_pnl, daily_pnl)
            daily_trading_paused, pause_reason = should_pause_new_entries(daily_pnl, peak_daily_pnl)

            if not in_position and action in ["BUY_LONG", "SELL_SHORT"] and (
                daily_trading_paused or not profile.permits_entry(action, current_time)
            ):
                action = "WAIT"

            if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:
                pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
                quantity = int(signal_data.get("suggested_qty", CONFIG["LOT_SIZE"]))
                entry_price = current_price * (1 + (CONFIG["SLIPPAGE_BPS"] if pos_type == "LONG" else -CONFIG["SLIPPAGE_BPS"]))
                stop_loss_price, target_price = calculate_entry_levels(entry_price, pos_type, signal_data)
                risk_budget = get_new_entry_risk_budget(daily_pnl, peak_daily_pnl)
                risk_allowed, _ = is_trade_risk_allowed(entry_price, stop_loss_price, quantity, signal_data.get("brokerage_fee", params["brokerage_fee"]), risk_budget)
                if not risk_allowed:
                    pos_type = ""
                    quantity = 0
                    entry_price = 0.0
                    stop_loss_price = None
                    target_price = None
                    action = "WAIT"
                    continue
                entry_data = signal_data
                in_position = True
                continue

            if not in_position:
                continue

            stop_loss_price = update_trailing_stop(current_price, entry_price, pos_type, stop_loss_price, entry_data)

            exit_reason = None
            if stop_loss_price is not None and ((pos_type == "LONG" and current_price <= stop_loss_price) or (pos_type == "SHORT" and current_price >= stop_loss_price)):
                exit_reason = "EXIT_SL"
            elif target_price is not None and ((pos_type == "LONG" and current_price >= target_price) or (pos_type == "SHORT" and current_price <= target_price)):
                exit_reason = "EXIT_TARGET"
            elif action.startswith("EXIT"):
                exit_reason = action

            if exit_reason is None:
                continue

            exit_price = current_price * (1 - (CONFIG["SLIPPAGE_BPS"] if pos_type == "LONG" else -CONFIG["SLIPPAGE_BPS"]))
            _, net_pnl = calculate_trade_pnl(entry_price, exit_price, pos_type, quantity, entry_data.get("brokerage_fee", params["brokerage_fee"]))
            pnls.append(net_pnl)
            daily_pnl += net_pnl
            peak_daily_pnl = max(peak_daily_pnl, daily_pnl)
            in_position = False
            pos_type = ""
            entry_price = 0.0
            quantity = 0
            stop_loss_price = None
            target_price = None
            entry_data = {}

    trades = len(pnls)
    total_pnl = round(sum(pnls), 2)
    win_rate = round(((sum(1 for value in pnls if value > 0) / trades) * 100), 2) if trades else 0.0
    avg_pnl = round((total_pnl / trades), 2) if trades else 0.0
    return {
        "trades": trades,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
    }


def build_candidate_trading_profiles():
    candidates = []
    seen = set()

    for strategy_name in ("strategy_1", "strategy_2", "strategy_3", "strategy_4"):
        for entry_start, entry_end in ((555, 915), (585, 870), (600, 840), (600, 825)):
            for skip_midday in (False, True):
                for allow_long, allow_short in ((True, True), (True, False), (False, True)):
                    key = (strategy_name, entry_start, entry_end, skip_midday, allow_long, allow_short)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        TradingProfile(
                            strategy_name=strategy_name,
                            entry_start_minute=entry_start,
                            entry_end_minute=entry_end,
                            skip_midday=skip_midday,
                            allow_long=allow_long,
                            allow_short=allow_short,
                            source="adaptive",
                        )
                    )

    return candidates


def resolve_trading_profile():
    fallback_profile = build_default_trading_profile()

    if not CONFIG["AUTO_TUNE_FROM_LOCAL_DATA"]:
        print(f"🧭 Adaptive tuning disabled. Using configured profile: {fallback_profile.describe()}")
        return fallback_profile

    records_by_day, used_files = load_local_price_history_records()
    if len(records_by_day) < CONFIG["MIN_LOCAL_TRAINING_FILES"]:
        print(
            f"🧭 Adaptive tuning skipped. Found {len(records_by_day)} local price-history files, "
            f"need at least {CONFIG['MIN_LOCAL_TRAINING_FILES']}."
        )
        print(f"   Using configured profile: {fallback_profile.describe()}")
        return fallback_profile

    candidate_profiles = build_candidate_trading_profiles()
    signal_cache = precompute_strategy_signals(
        records_by_day,
        sorted({profile.strategy_name for profile in candidate_profiles}),
    )

    minimum_trades = max(4, len(records_by_day) - 1)
    scored_profiles = []
    for profile in candidate_profiles:
        stats = simulate_profile_from_cache(profile, signal_cache)
        if stats["trades"] < minimum_trades:
            continue
        scored_profiles.append((stats, profile))

    baseline_stats = simulate_profile_from_cache(fallback_profile, signal_cache)
    if not scored_profiles:
        print("🧭 Adaptive tuning could not find a profile with enough sample trades.")
        print(
            f"   Baseline profile: {fallback_profile.describe()} | "
            f"{baseline_stats['trades']} trades | PnL ₹{baseline_stats['total_pnl']:,.2f}"
        )
        return fallback_profile

    best_stats, best_profile = max(
        scored_profiles,
        key=lambda item: (item[0]["total_pnl"], item[0]["win_rate"], item[0]["avg_pnl"]),
    )

    selected_profile = TradingProfile(
        strategy_name=best_profile.strategy_name,
        entry_start_minute=best_profile.entry_start_minute,
        entry_end_minute=best_profile.entry_end_minute,
        skip_midday=best_profile.skip_midday,
        allow_long=best_profile.allow_long,
        allow_short=best_profile.allow_short,
        source=f"adaptive ({len(used_files)} sessions)",
    )

    print(f"🧪 Adaptive tuning used {len(used_files)} local sessions")
    print(
        f"   Baseline: {fallback_profile.describe()} | "
        f"{baseline_stats['trades']} trades | PnL ₹{baseline_stats['total_pnl']:,.2f}"
    )
    print(
        f"   Selected: {selected_profile.describe()} | "
        f"{best_stats['trades']} trades | PnL ₹{best_stats['total_pnl']:,.2f} | "
        f"Win rate {best_stats['win_rate']:.1f}%"
    )
    return selected_profile


def build_candles_frame_from_records(records):
    if not records:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        
    candles = pd.DataFrame(records).copy()
    
    # Safely ensure 'Close' exists without raising KeyError
    if "Close" not in candles.columns:
        candles["Close"] = candles.get("Price", 0.0)
        
    candles["Open"] = pd.to_numeric(candles.get("Open", candles["Close"]), errors="coerce").fillna(candles["Close"])
    candles["High"] = pd.to_numeric(candles.get("High", candles["Close"]), errors="coerce").fillna(candles["Close"])
    candles["Low"] = pd.to_numeric(candles.get("Low", candles["Close"]), errors="coerce").fillna(candles["Close"])
    candles["Close"] = pd.to_numeric(candles["Close"], errors="coerce")
    candles["Volume"] = pd.to_numeric(candles.get("Volume", 0.0), errors="coerce").fillna(0.0)
    
    return candles[["Open", "High", "Low", "Close", "Volume"]]


def get_recent_candles_from_records(data_records, index, lookback=60):
    start_index = max(0, index - lookback + 1)
    return build_candles_frame_from_records(data_records[start_index:index + 1])


def get_recent_candles_from_market_df(df, lookback=60):
    window = df.tail(lookback).reset_index(drop=True)
    return build_candles_frame_from_records(window.to_dict("records"))


def calculate_entry_levels(entry_price, pos_type, signal_data):
    stop_loss_pct = float(signal_data.get("stop_loss_pct", risk_management()["stop_loss_pct"]))
    target_pct = float(signal_data.get("target_pct", risk_management()["target_pct"]))
    if pos_type == "LONG":
        stop_loss_price = entry_price * (1 - stop_loss_pct)
        target_price = entry_price * (1 + target_pct)
    else:
        stop_loss_price = entry_price * (1 + stop_loss_pct)
        target_price = entry_price * (1 - target_pct)
    return stop_loss_price, target_price


def update_trailing_stop(current_price, entry_price, pos_type, stop_loss_price, entry_data):
    breakeven_pct = float(entry_data.get("breakeven_pct", risk_management()["breakeven_pct"]))
    trail_distance = float(entry_data.get("trail_distance", risk_management()["trail_distance"]))
    stop_loss_pct = float(entry_data.get("stop_loss_pct", risk_management()["stop_loss_pct"]))
    
    pnl_pct = ((current_price - entry_price) / entry_price) if pos_type == "LONG" else ((entry_price - current_price) / entry_price)

    if pos_type == "LONG":
        # Always trail from current moment price to constantly reduce initial risk
        new_sl = max(stop_loss_price or 0.0, current_price * (1 - stop_loss_pct))
        if pnl_pct >= breakeven_pct:
            new_sl = max(new_sl, entry_price) # Guarantee breakeven
            new_sl = max(new_sl, current_price * (1 - trail_distance)) # Tighten trail to lock profit
        return new_sl

    # SHORT
    new_sl = min(stop_loss_price or float('inf'), current_price * (1 + stop_loss_pct))
    if pnl_pct >= breakeven_pct:
        new_sl = min(new_sl, entry_price) # Guarantee breakeven
        new_sl = min(new_sl, current_price * (1 + trail_distance)) # Tighten trail to lock profit
    return new_sl


def calculate_trade_pnl(entry_price, exit_price, pos_type, quantity, brokerage_fee):
    points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
    net_pnl = (points * quantity) - brokerage_fee
    return points, net_pnl


def get_daily_loss_limit_amount():
    return CONFIG["CAPITAL"] * risk_management()["daily_loss_limit_pct"]


def get_max_loss_per_trade_amount():
    return risk_management(capital=CONFIG["CAPITAL"])["max_loss_per_trade_amount"]


def estimate_planned_trade_risk(entry_price, stop_loss_price, quantity, brokerage_fee):
    if quantity <= 0 or stop_loss_price is None:
        return float("inf")
    return abs(entry_price - stop_loss_price) * quantity + brokerage_fee


def get_new_entry_risk_budget(daily_pnl=0.0, peak_daily_pnl=0.0):
    base_budget = get_max_loss_per_trade_amount()
    params = risk_management(capital=CONFIG["CAPITAL"])
    if peak_daily_pnl >= params["profit_protection_start_amount"]:
        protected_floor = peak_daily_pnl * (1 - params["profit_giveback_pct"])
        return max(0.0, min(base_budget, daily_pnl - protected_floor))
    return base_budget


def is_trade_risk_allowed(entry_price, stop_loss_price, quantity, brokerage_fee, risk_budget=None):
    planned_risk = estimate_planned_trade_risk(entry_price, stop_loss_price, quantity, brokerage_fee)
    max_allowed_risk = get_max_loss_per_trade_amount() if risk_budget is None else min(get_max_loss_per_trade_amount(), risk_budget)
    return planned_risk <= max_allowed_risk, planned_risk


def should_pause_new_entries(daily_pnl, peak_daily_pnl):
    params = risk_management(capital=CONFIG["CAPITAL"])
    if daily_pnl <= -get_daily_loss_limit_amount():
        return True, "DAILY_LOSS_LIMIT"
    if peak_daily_pnl >= params["profit_protection_start_amount"]:
        protected_floor = peak_daily_pnl * (1 - params["profit_giveback_pct"])
        if daily_pnl < protected_floor:
            return True, "PROFIT_PROTECTION"
    return False, ""


def calculate_performance_stats(report_df):
    if report_df.empty:
        return {"profit_factor": 0.0, "max_drawdown": 0.0}

    gross_profit = report_df.loc[report_df["Net_PnL"] > 0, "Net_PnL"].sum()
    gross_loss = abs(report_df.loc[report_df["Net_PnL"] < 0, "Net_PnL"].sum())
    profit_factor = round(float(gross_profit / gross_loss), 2) if gross_loss > 0 else float("inf")
    equity_curve = report_df["Net_PnL"].cumsum()
    drawdown = equity_curve - equity_curve.cummax()
    max_drawdown = round(float(abs(drawdown.min())), 2) if not drawdown.empty else 0.0
    return {
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
    }


def run_profile_backtest(data_records, trading_profile):
    trades = []
    price_history = []
    in_position = False
    pos_type, entry_price, entry_time = "", 0.0, None
    entry_data = {}
    quantity = 0
    stop_loss_price = None
    target_price = None
    current_day = None
    daily_pnl = 0.0
    peak_daily_pnl = 0.0
    daily_trading_paused = False
    pause_reason = ""

    for i in range(MIN_SIGNAL_CANDLES - 1, len(data_records)):
        row = data_records[i]
        now_time, now_close = row["Datetime"], float(row["Close"])
        params = risk_management()

        if current_day != now_time.date():
            if in_position and i > 0:
                previous_close = float(data_records[i - 1]["Close"])
                exit_price = previous_close * (1 - (CONFIG["SLIPPAGE_BPS"] if pos_type == "LONG" else -CONFIG["SLIPPAGE_BPS"]))
                points, net_pnl = calculate_trade_pnl(entry_price, exit_price, pos_type, quantity, entry_data.get("brokerage_fee", params["brokerage_fee"]))
                daily_pnl += net_pnl
                peak_daily_pnl = max(peak_daily_pnl, daily_pnl)
                trades.append({
                    "Trade_ID": f"{trading_profile.strategy_name.upper()}_{len(trades)+1}",
                    "Entry_Time": entry_time,
                    "Exit_Time": data_records[i - 1]["Datetime"],
                    "Type": pos_type,
                    "Qty": quantity,
                    "Entry_Price": round(entry_price, 2),
                    "Exit_Price": round(exit_price, 2),
                    "Points": round(points, 2),
                    "Net_PnL": round(net_pnl, 2),
                    "Exit_Reason": "DAY_CLOSE",
                    "Entry_RSI": entry_data.get("rsi"),
                    "Entry_EMA_F": entry_data.get("ema_f"),
                    "Exit_RSI": None,
                    "Entry_Score": entry_data.get("entry_score"),
                    "Strategy": trading_profile.strategy_name,
                    "Planned_Risk": round(entry_data.get("planned_risk", 0.0), 2),
                    "Daily_PnL_After": round(daily_pnl, 2),
                    "Risk_Allowed": True,
                    "Session_Stop": pause_reason,
                })
            in_position = False
            pos_type, entry_price, entry_time = "", 0.0, None
            entry_data = {}
            quantity = 0
            stop_loss_price = None
            target_price = None
            current_day = now_time.date()
            daily_pnl = 0.0
            peak_daily_pnl = 0.0
            daily_trading_paused = False
            pause_reason = ""

        price_history.append({
            "DateTime": now_time,
            "Price": now_close,
            "High": float(row["High"]),
            "Low": float(row["Low"]),
            "Volume": float(row["Volume"]) if "Volume" in row else 0,
            "Signal": None,
            "RSI": None,
            "RSI_FAST": None,
            "EMA_FAST": None,
            "SLOPE": None,
            "PERCENT_B": None,
            "ATR": None,
            "Volume_Ratio": None,
            "Entry_Score": None,
            "REGIME": None,
            "Strategy": trading_profile.strategy_name,
            "Stop_Loss": stop_loss_price,
            "Target": target_price,
        })

        recent_candles = get_recent_candles_from_records(data_records, i, lookback=60)
        price_window = recent_candles["Close"].tolist()
        signal_data = calculate_signals(
            price_list=price_window,
            current_time=now_time,
            position=(1 if pos_type == "LONG" else -1) if in_position else 0,
            entry_price=entry_price,
            strategy_name=trading_profile.strategy_name,
            candles_df=recent_candles,
            capital=CONFIG["CAPITAL"],
            lot_size=CONFIG["LOT_SIZE"],
        )
        action = signal_data.get("action", "WAIT")
        price_history[-1].update({
            "Signal": action,
            "RSI": signal_data.get("rsi"),
            "RSI_FAST": signal_data.get("rsi_fast"),
            "EMA_FAST": signal_data.get("ema_f"),
            "SLOPE": signal_data.get("slope"),
            "PERCENT_B": signal_data.get("percent_b"),
            "ATR": signal_data.get("atr"),
            "Volume_Ratio": signal_data.get("volume_ratio"),
            "Entry_Score": signal_data.get("entry_score"),
            "REGIME": signal_data.get("regime"),
            "Stop_Loss": stop_loss_price,
            "Target": target_price,
        })

        peak_daily_pnl = max(peak_daily_pnl, daily_pnl)
        daily_trading_paused, pause_reason = should_pause_new_entries(daily_pnl, peak_daily_pnl)

        if not in_position and action in ["BUY_LONG", "SELL_SHORT"] and (
            daily_trading_paused or not trading_profile.permits_entry(action, now_time)
        ):
            action = "WAIT"

        if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:
            quantity = int(signal_data.get("suggested_qty", CONFIG["LOT_SIZE"]))
            in_position = True
            pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
            entry_price = now_close * (1 + (CONFIG["SLIPPAGE_BPS"] if pos_type == "LONG" else -CONFIG["SLIPPAGE_BPS"]))
            entry_time = now_time
            entry_data = signal_data
            stop_loss_price, target_price = calculate_entry_levels(entry_price, pos_type, signal_data)
            risk_budget = get_new_entry_risk_budget(daily_pnl, peak_daily_pnl)
            risk_allowed, planned_risk = is_trade_risk_allowed(entry_price, stop_loss_price, quantity, signal_data.get("brokerage_fee", params["brokerage_fee"]), risk_budget)
            if not risk_allowed:
                in_position = False
                pos_type = ""
                entry_price = 0.0
                entry_time = None
                entry_data = {}
                quantity = 0
                stop_loss_price = None
                target_price = None
                continue
            entry_data["planned_risk"] = planned_risk
            continue

        if not in_position:
            continue

        stop_loss_price = update_trailing_stop(now_close, entry_price, pos_type, stop_loss_price, entry_data)

        exit_reason = None
        if stop_loss_price is not None and ((pos_type == "LONG" and now_close <= stop_loss_price) or (pos_type == "SHORT" and now_close >= stop_loss_price)):
            exit_reason = "EXIT_SL"
        elif target_price is not None and ((pos_type == "LONG" and now_close >= target_price) or (pos_type == "SHORT" and now_close <= target_price)):
            exit_reason = "EXIT_TARGET"
        elif action.startswith("EXIT"):
            exit_reason = action

        if exit_reason is None:
            continue

        exit_price = now_close * (1 - (CONFIG["SLIPPAGE_BPS"] if pos_type == "LONG" else -CONFIG["SLIPPAGE_BPS"]))
        points, net_pnl = calculate_trade_pnl(entry_price, exit_price, pos_type, quantity, entry_data.get("brokerage_fee", params["brokerage_fee"]))
        daily_pnl += net_pnl
        peak_daily_pnl = max(peak_daily_pnl, daily_pnl)

        trades.append({
            "Trade_ID": f"{trading_profile.strategy_name.upper()}_{len(trades)+1}",
            "Entry_Time": entry_time,
            "Exit_Time": now_time,
            "Type": pos_type,
            "Qty": quantity,
            "Entry_Price": round(entry_price, 2),
            "Exit_Price": round(exit_price, 2),
            "Points": round(points, 2),
            "Net_PnL": round(net_pnl, 2),
            "Exit_Reason": exit_reason,
            "Entry_RSI": entry_data.get("rsi"),
            "Entry_EMA_F": entry_data.get("ema_f"),
            "Exit_RSI": signal_data.get("rsi"),
            "Entry_Score": entry_data.get("entry_score"),
            "Strategy": trading_profile.strategy_name,
            "Planned_Risk": round(entry_data.get("planned_risk", 0.0), 2),
            "Daily_PnL_After": round(daily_pnl, 2),
            "Risk_Allowed": True,
            "Session_Stop": pause_reason,
        })
        in_position = False
        pos_type = ""
        entry_price = 0.0
        entry_time = None
        entry_data = {}
        quantity = 0
        stop_loss_price = None
        target_price = None

    if in_position and data_records:
        final_close = float(data_records[-1]["Close"])
        final_time = data_records[-1]["Datetime"]
        exit_price = final_close * (1 - (CONFIG["SLIPPAGE_BPS"] if pos_type == "LONG" else -CONFIG["SLIPPAGE_BPS"]))
        points, net_pnl = calculate_trade_pnl(entry_price, exit_price, pos_type, quantity, entry_data.get("brokerage_fee", risk_management()["brokerage_fee"]))
        daily_pnl += net_pnl
        trades.append({
            "Trade_ID": f"{trading_profile.strategy_name.upper()}_{len(trades)+1}",
            "Entry_Time": entry_time,
            "Exit_Time": final_time,
            "Type": pos_type,
            "Qty": quantity,
            "Entry_Price": round(entry_price, 2),
            "Exit_Price": round(exit_price, 2),
            "Points": round(points, 2),
            "Net_PnL": round(net_pnl, 2),
            "Exit_Reason": "BACKTEST_END",
            "Entry_RSI": entry_data.get("rsi"),
            "Entry_EMA_F": entry_data.get("ema_f"),
            "Exit_RSI": None,
            "Entry_Score": entry_data.get("entry_score"),
            "Strategy": trading_profile.strategy_name,
            "Planned_Risk": round(entry_data.get("planned_risk", 0.0), 2),
            "Daily_PnL_After": round(daily_pnl, 2),
            "Risk_Allowed": True,
            "Session_Stop": pause_reason,
        })

    report_df = build_trade_report_frame(trades)
    total_pnl = round(report_df["Net_PnL"].sum(), 2) if not report_df.empty else 0.0
    win_rate = round(((report_df["Net_PnL"] > 0).sum() / len(report_df)) * 100, 2) if not report_df.empty else 0.0
    avg_pnl = round(report_df["Net_PnL"].mean(), 2) if not report_df.empty else 0.0

    return {
        "df": report_df,
        "price_history_df": pd.DataFrame(price_history),
        "total_pnl": total_pnl,
        "trades": len(report_df),
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "stats": calculate_performance_stats(report_df),
        "profile": trading_profile,
    }

def import_smart_api():
    try:
        import pyotp
        from SmartApi import SmartConnect
    except ImportError as e:
        raise RuntimeError(f"Angel SmartAPI dependencies not installed: {e}") from e
    return pyotp, SmartConnect


def create_angel_session():
    missing = [
        name for name, value in [
            ("ANGEL_API_KEY", API_KEY),
            ("ANGEL_CLIENT_ID", CLIENT_ID),
            ("ANGEL_PASSWORD", PASSWORD),
            ("ANGEL_TOTP_SECRET", TOTP_SECRET),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing Angel credentials: {', '.join(missing)}")

    pyotp, SmartConnect = import_smart_api()
    smart_api = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    login_response = smart_api.generateSession(CLIENT_ID, PASSWORD, totp)
    if not login_response.get("status"):
        raise RuntimeError(f"Angel One login failed: {login_response}")
    return smart_api


def close_angel_session(smart_api):
    if smart_api is None:
        return
    try:
        smart_api.terminateSession(CLIENT_ID)
    except Exception:
        pass


def get_market_window(now=None):
    now = now or datetime.now()
    market_open = datetime.combine(now.date(), dt_time(9, 15))
    market_close = datetime.combine(now.date(), dt_time(15, 15))
    return market_open, market_close


def normalize_market_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("Asia/Kolkata").tz_localize(None)
    return timestamp


def extract_ltp_value(payload, tradingsymbol=None):
    if payload is None:
        return None
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, str):
        try:
            return float(payload)
        except ValueError:
            return None
    if isinstance(payload, dict):
        if tradingsymbol and tradingsymbol in payload:
            return extract_ltp_value(payload[tradingsymbol], tradingsymbol)
        if "data" in payload:
            value = extract_ltp_value(payload["data"], tradingsymbol)
            if value is not None:
                return value
        for key in ("ltp", "LTP", "last_traded_price", "close", "Close"):
            if key in payload:
                return extract_ltp_value(payload[key], tradingsymbol)
    return None


def fetch_angel_candles(smart_api, exchange, symbol_token, interval, from_dt, to_dt):
    if not hasattr(smart_api, "getCandleData"):
        raise RuntimeError("Installed SmartAPI client does not expose getCandleData")

    historic_params = {
        "exchange": exchange,
        "symboltoken": str(symbol_token),
        "interval": interval,
        "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
        "todate": to_dt.strftime("%Y-%m-%d %H:%M"),
    }
    response = smart_api.getCandleData(historic_params)
    if isinstance(response, dict) and response.get("status") is False:
        message = response.get("message") or response.get("errorcode") or "Angel candle request failed"
        raise RuntimeError(message)
    raw_rows = response.get("data") if isinstance(response, dict) else None
    if not raw_rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    records = []
    for row in raw_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        records.append({
            "DateTime": normalize_market_timestamp(row[0]),
            "Open": float(row[1]),
            "High": float(row[2]),
            "Low": float(row[3]),
            "Close": float(row[4]),
            "Volume": float(row[5]) if len(row) > 5 and row[5] not in (None, "") else 0.0,
        })

    if not records:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    df = pd.DataFrame(records)
    df = df.drop_duplicates(subset=["DateTime"]).sort_values("DateTime")
    df = df.set_index("DateTime")
    return df


def get_live_price(smart_api, symbol, exchange, symbol_token):
    """Fetch LTP from Angel One without falling back to delayed third-party data."""
    if hasattr(smart_api, "ltpData"):
        try:
            quote = smart_api.ltpData(exchange, symbol, str(symbol_token))
            value = extract_ltp_value(quote, symbol)
            if value is not None:
                return value
        except Exception:
            pass

    if hasattr(smart_api, "getLTP"):
        for args in ((exchange, symbol, str(symbol_token)), (exchange, symbol)):
            try:
                quote = smart_api.getLTP(*args)
                value = extract_ltp_value(quote, symbol)
                if value is not None:
                    return value
            except TypeError:
                continue
            except Exception:
                pass

    if hasattr(smart_api, "get_quotes"):
        try:
            quote = smart_api.get_quotes(exchange, [symbol])
            value = extract_ltp_value(quote, symbol)
            if value is not None:
                return value
        except Exception:
            pass

    return None


def fetch_backtest_market_data(symbol, start_dt, end_dt, interval="5m"):
    chunk_frames = []
    cursor = start_dt
    chunk_days = 55 if interval.endswith("m") else 180

    while cursor < end_dt:
        chunk_end = min(cursor + timedelta(days=chunk_days), end_dt)
        chunk = yf.download(
            symbol,
            start=cursor.strftime("%Y-%m-%d"),
            end=chunk_end.strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
        )
        if not chunk.empty:
            chunk_frames.append(chunk)
        cursor = chunk_end

    if not chunk_frames:
        return pd.DataFrame()

    combined = pd.concat(chunk_frames)
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def finalize_trading_session(trades, price_history, trade_path, price_path, source_label):
    if trades:
        report_df, price_history_df = save_trade_and_price_files(trades, price_history, trade_path, price_path)
        print(f"\n✅ {source_label} COMPLETE. Trades: {len(report_df)} | Total PnL: ₹{report_df['Net_PnL'].sum():,.2f}")
        print(f"   Price history written to {price_path}")
        print(f"   Trades written to {trade_path}")
        return report_df, price_history_df

    report_df, price_history_df = save_trade_and_price_files([], price_history, trade_path, price_path)
    print(f"\n⚠️ No {source_label.lower()} trades were generated today.")
    print(f"   Empty trade report written to {trade_path}")
    print(f"   Price history still saved to {price_path}")
    return report_df, price_history_df


def send_session_email():
    try:
        from send_email_report import send_performance_email
        send_performance_email()
        print("✅ Email report sent")
    except Exception as e:
        print(f"❌ Email failed: {e}")


def place_order(smart_api, symbol, side, quantity, price, exchange="NSE", symbol_token="99926000"):
    """Place an order via Angel One API."""
    try:
        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": str(symbol_token),
            "transactiontype": side,
            "exchange": exchange,
            "ordertype": "LIMIT",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": str(price),
            "quantity": str(quantity)
        }
        response = smart_api.placeOrder(order_params)
        return response
    except Exception as e:
        print(f"Order placement failed: {e}")
        return None


def calculate_exit_price(entry_price, is_long, slippage, short=False):
    if is_long:
        return entry_price * (1 - slippage)
    return entry_price * (1 + slippage)


def run_live_trading(): # Master Real Money Session Loop
    """Run live trading during market hours and exit after market close.""" # Docstring
    print("🚀 Starting LIVE TRADING MODE") # Print Start Event Status

    try: # Begin API Boot
        smart_api = create_angel_session() # Launch and bind Angel API Session credentials
    except Exception as e: # Handle critical failures
        print(f"❌ {e}") # Print error to user
        return # Abandon startup

    print("✅ Angel One login successful") # Print Success Event
    print(f"📡 Using Angel market data for {CONFIG['MARKET_DATA_SYMBOL']} ({CONFIG['MARKET_DATA_INTERVAL']})") # Display charting parameters
    trading_profile = resolve_trading_profile() # Fetch and configure local or adaptive configurations
    strategy_name = trading_profile.strategy_name # Bind strategy context
    print(f"🧠 Active forward profile: {trading_profile.describe()} [{trading_profile.source}]") # Display configuration context

    trades = [] # Array tracking session trade details
    price_history = [] # Array tracking charting ticks
    in_position = False # State flag
    pos_type, entry_price, entry_time = "", 0.0, None # Blank tracking variables
    entry_data = {} # Blank logic properties
    quantity = 0 # Empty sizing cache
    stop_loss_price = None # Blank SL cache
    target_price = None # Blank TP cache
    last_candle_time = None # Loop repetition state checker
    session_date = None # Session rollover state checker
    daily_pnl = 0.0 # Day-to-date money tracker
    peak_daily_pnl = 0.0 # Highest closed PnL reached during this session
    daily_trading_paused = False # Flag for blown daily-loss thresholds
    pause_reason = "" # Why entries are paused

    try: # Begin primary live trading execution loop
        while True: # Keep spinning indefinitely (until break triggered or crash)
            now = datetime.now() # Get current actual datetime
            market_open, market_close = get_market_window(now) # Find actual opening/closing benchmarks for the active day
            if now.weekday() < 5 and session_date != now.date(): # Reset logic if rolling into a new weekday
                session_date = now.date() # Bind new session tracker
                daily_pnl = 0.0 # Reset tracked Day-to-date PnL
                peak_daily_pnl = 0.0 # Reset session profit watermark
                daily_trading_paused = False # Enable active entries again
                pause_reason = "" # Clear session pause reason

            if now >= market_close: # If market close logic overrides
                print("🏁 Market closed. Sending final report...") # Trigger EOD processing
                if in_position: # Force clean up of un-exited orders (Auto Square-Off mapping)
                    current_price = get_live_price( # Request current price directly
                        smart_api, # API object
                        CONFIG["TRADE_SYMBOL"], # Forward context symbol
                        CONFIG["TRADE_EXCHANGE"], # Forward context exchange
                        CONFIG["TRADE_SYMBOL_TOKEN"], # Forward context token
                    ) # Receive LTP
                    if current_price is not None: # Confirm LTP resolved
                        exit_price = calculate_exit_price(current_price, pos_type == "LONG", CONFIG['SLIPPAGE_BPS']) # Process theoretical real exit cost
                        
                        # --- CRITICAL FIX: ACTUALLY PLACE THE LIVE BROKER ORDER ---
                        exit_side = "SELL" if pos_type == "LONG" else "BUY"
                        exit_order = place_order(
                            smart_api,
                            CONFIG["TRADE_SYMBOL"],
                            exit_side,
                            quantity or CONFIG["LOT_SIZE"],
                            exit_price,
                            exchange=CONFIG["TRADE_EXCHANGE"],
                            symbol_token=CONFIG["TRADE_SYMBOL_TOKEN"],
                        )
                        if exit_order:
                            print(f"✅ Placed {exit_side} EOD exit order for {CONFIG['TRADE_SYMBOL']} at {exit_price}")
                        else:
                            print(f"❌ Failed to place EOD exit order for {CONFIG['TRADE_SYMBOL']} at {exit_price}")
                        # ----------------------------------------------------------
                        
                        points, net_pnl = calculate_trade_pnl(entry_price, exit_price, pos_type, quantity or CONFIG["LOT_SIZE"], entry_data.get("brokerage_fee", risk_management()['brokerage_fee'])) # Map net math
                        trades.append({ # Log the un-exited EOD order into tracking file
                            "Trade_ID": f"ANGEL_{len(trades)+1}", # Append numeric log
                            "Entry_Time": entry_time, # Insert mapped values
                            "Exit_Time": now, # Insert current exiting time
                            "Type": pos_type, # Specify Long vs Short
                            "Qty": quantity or CONFIG["LOT_SIZE"], # Add lot constraints
                            "Entry_Price": round(entry_price, 2), # Snapshot value
                            "Exit_Price": round(exit_price, 2), # Snapshot value
                            "Points": round(points, 2), # Add math results
                            "Net_PnL": round(net_pnl, 2), # Add math results
                            "Exit_Reason": "MARKET_CLOSE", # Attribute force closure reason correctly
                            "Entry_RSI": entry_data.get('rsi'), # Include analytical metadata
                            "Entry_EMA_F": entry_data.get('ema_f'), # Include analytical metadata
                            "Exit_RSI": None, # Clean irrelevant field
                            "Entry_Score": entry_data.get("entry_score"), # Analytics field
                            "Strategy": strategy_name # Origin tracking
                        }) 
                finalize_trading_session(trades, price_history, CONFIG['OUTPUT_FILE'], CONFIG['PRICE_HISTORY_FILE'], "LIVE TRADING") # Run helper to compile outputs to CSV
                send_session_email() # Send Gmail wrapper report
                print("✅ Live trading session complete. Exiting...") # Show final line
                return # Break the function explicitly

            if now < market_open or now.weekday() >= 5:
                print(f"⏰ Outside market hours ({now.strftime('%H:%M')}). Waiting...")
                time.sleep(60)
                continue

            try:
                df = fetch_angel_candles(
                    smart_api,
                    CONFIG["MARKET_DATA_EXCHANGE"],
                    CONFIG["MARKET_DATA_SYMBOL_TOKEN"],
                    CONFIG["MARKET_DATA_INTERVAL"],
                    now - timedelta(days=CONFIG["CANDLE_LOOKBACK_DAYS"]),
                    now,
                )
                if df.empty or len(df) < MIN_SIGNAL_CANDLES:
                    print("⏳ Waiting for enough Angel candle history...")
                    time.sleep(CONFIG["MARKET_POLL_SECONDS"])
                    continue

                current_time = df.index[-1].to_pydatetime()
                if current_time.date() != now.date():
                    print("⏳ Waiting for today's first Angel candle...")
                    time.sleep(CONFIG["MARKET_POLL_SECONDS"])
                    continue

                current_price = get_live_price(
                    smart_api,
                    CONFIG["TRADE_SYMBOL"],
                    CONFIG["TRADE_EXCHANGE"],
                    CONFIG["TRADE_SYMBOL_TOKEN"],
                )
                if current_price is None:
                    current_price = float(df['Close'].iloc[-1])

                recent_candles = get_recent_candles_from_market_df(df, lookback=60)
                price_window = recent_candles['Close'].tolist()
                risk = risk_management()
                position_flag = 1 if pos_type == "LONG" else -1 if pos_type == "SHORT" else 0
                signal_data = calculate_signals(
                    price_list=price_window,
                    current_time=current_time,
                    position=position_flag,
                    entry_price=entry_price,
                    strategy_name=strategy_name,
                    candles_df=recent_candles,
                    capital=CONFIG["CAPITAL"],
                    lot_size=CONFIG["LOT_SIZE"],
                )
                action = signal_data.get('action', 'WAIT')
                is_new_candle = current_time != last_candle_time
                peak_daily_pnl = max(peak_daily_pnl, daily_pnl)
                daily_trading_paused, pause_reason = should_pause_new_entries(daily_pnl, peak_daily_pnl)

                if in_position:
                    stop_loss_price = update_trailing_stop(current_price, entry_price, pos_type, stop_loss_price, entry_data)

                    exit_reason = None
                    if stop_loss_price is not None:
                        if (pos_type == "LONG" and current_price <= stop_loss_price) or (pos_type == "SHORT" and current_price >= stop_loss_price):
                            exit_reason = "EXIT_SL"
                    if exit_reason is None and target_price is not None:
                        if (pos_type == "LONG" and current_price >= target_price) or (pos_type == "SHORT" and current_price <= target_price):
                            exit_reason = "EXIT_TARGET"
                    if exit_reason is None and is_new_candle and action.startswith("EXIT"):
                        exit_reason = action

                    if exit_reason is not None:
                        exit_price = calculate_exit_price(current_price, pos_type == "LONG", CONFIG['SLIPPAGE_BPS'])
                        points, net_pnl = calculate_trade_pnl(entry_price, exit_price, pos_type, quantity or CONFIG["LOT_SIZE"], entry_data.get("brokerage_fee", risk['brokerage_fee']))
                        daily_pnl += net_pnl
                        peak_daily_pnl = max(peak_daily_pnl, daily_pnl)
                        trades.append({
                            "Trade_ID": f"ANGEL_{len(trades)+1}",
                            "Entry_Time": entry_time,
                            "Exit_Time": now,
                            "Type": pos_type,
                            "Qty": quantity or CONFIG["LOT_SIZE"],
                            "Entry_Price": round(entry_price, 2),
                            "Exit_Price": round(exit_price, 2),
                            "Points": round(points, 2),
                            "Net_PnL": round(net_pnl, 2),
                            "Exit_Reason": exit_reason,
                            "Entry_RSI": entry_data.get('rsi'),
                            "Entry_EMA_F": entry_data.get('ema_f'),
                            "Exit_RSI": signal_data.get('rsi'),
                            "Entry_Score": entry_data.get("entry_score"),
                            "Strategy": strategy_name,
                            "Planned_Risk": round(entry_data.get("planned_risk", 0.0), 2),
                            "Daily_PnL_After": round(daily_pnl, 2),
                            "Risk_Allowed": True,
                            "Session_Stop": pause_reason,
                        })

                        exit_side = "SELL" if pos_type == "LONG" else "BUY"
                        exit_order = place_order(
                            smart_api,
                            CONFIG["TRADE_SYMBOL"],
                            exit_side,
                            quantity or CONFIG['LOT_SIZE'],
                            exit_price,
                            exchange=CONFIG["TRADE_EXCHANGE"],
                            symbol_token=CONFIG["TRADE_SYMBOL_TOKEN"],
                        )
                        if exit_order:
                            print(f"✅ Placed {exit_side} exit order for {CONFIG['TRADE_SYMBOL']} at {exit_price}")
                        else:
                            print(f"❌ Failed to place exit order for {CONFIG['TRADE_SYMBOL']} at {exit_price}")

                        in_position = False
                        pos_type = ""
                        entry_price = 0.0
                        entry_time = None
                        entry_data = {}
                        quantity = 0
                        stop_loss_price = None
                        target_price = None

                if is_new_candle:
                    candle = df.iloc[-1]
                    price_history.append({
                        "DateTime": current_time,
                        "Price": current_price,
                        "High": float(candle['High']),
                        "Low": float(candle['Low']),
                        "Volume": float(candle['Volume']) if 'Volume' in candle.index else 0,
                        "Signal": action,
                        "RSI": signal_data.get('rsi'),
                        "RSI_FAST": signal_data.get('rsi_fast'),
                        "EMA_FAST": signal_data.get('ema_f'),
                        "SLOPE": signal_data.get('slope'),
                        "PERCENT_B": signal_data.get('percent_b') if 'percent_b' in signal_data else None,
                        "ATR": signal_data.get("atr"),
                        "Volume_Ratio": signal_data.get("volume_ratio"),
                        "Entry_Score": signal_data.get("entry_score"),
                        "REGIME": signal_data.get('regime'),
                        "Strategy": strategy_name,
                        "Stop_Loss": stop_loss_price,
                        "Target": target_price
                    })
                    last_candle_time = current_time

                if not in_position and is_new_candle and action in ["BUY_LONG", "SELL_SHORT"] and not daily_trading_paused and trading_profile.permits_entry(action, current_time):
                    pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
                    quantity = int(signal_data.get("suggested_qty", CONFIG["LOT_SIZE"]))
                    entry_price = current_price * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                    entry_time = now
                    entry_data = signal_data
                    stop_loss_price, target_price = calculate_entry_levels(entry_price, pos_type, signal_data)
                    risk_budget = get_new_entry_risk_budget(daily_pnl, peak_daily_pnl)
                    risk_allowed, planned_risk = is_trade_risk_allowed(entry_price, stop_loss_price, quantity, signal_data.get("brokerage_fee", risk["brokerage_fee"]), risk_budget)
                    if not risk_allowed:
                        print(f"🛡️ Skipping live entry: planned risk ₹{planned_risk:.2f} exceeds allowed risk ₹{risk_budget:.2f}")
                        pos_type = ""
                        entry_price = 0.0
                        entry_time = None
                        entry_data = {}
                        quantity = 0
                        stop_loss_price = None
                        target_price = None
                        time.sleep(CONFIG["MARKET_POLL_SECONDS"])
                        continue
                    entry_data["planned_risk"] = planned_risk
                    side = "BUY" if pos_type == "LONG" else "SELL"
                    order_response = place_order(
                        smart_api,
                        CONFIG["TRADE_SYMBOL"],
                        side,
                        quantity,
                        entry_price,
                        exchange=CONFIG["TRADE_EXCHANGE"],
                        symbol_token=CONFIG["TRADE_SYMBOL_TOKEN"],
                    )
                    if order_response:
                        in_position = True
                        print(f"✅ Entered {pos_type} on {CONFIG['TRADE_SYMBOL']} at {entry_price:.2f} | Qty {quantity} | SL {stop_loss_price:.2f} | Target {target_price:.2f}")
                    else:
                        print("❌ Live entry failed. Waiting for next signal.")
                        pos_type = ""
                        entry_price = 0.0
                        entry_time = None
                        entry_data = {}
                        quantity = 0
                        stop_loss_price = None
                        target_price = None

                time.sleep(CONFIG["MARKET_POLL_SECONDS"])
            except Exception as e:
                print(f"❌ Live trading error: {e}")
                time.sleep(60)
    finally:
        close_angel_session(smart_api)


def build_trade_report_frame(trades):
    if not trades:
        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)
    return pd.DataFrame(trades)


def build_price_history_frame(price_history):
    if not price_history:
        return pd.DataFrame(columns=PRICE_HISTORY_COLUMNS)
    return pd.DataFrame(price_history)


def save_trade_and_price_files(trades, price_history, trade_path, price_path):
    report_df = build_trade_report_frame(trades)
    report_df.to_csv(trade_path, index=False)
    price_history_df = build_price_history_frame(price_history)
    price_history_df.to_csv(price_path, index=False)
    return report_df, price_history_df


def reset_paper_session_files(session_date):
    save_trade_and_price_files([], [], CONFIG['PAPER_OUTPUT_FILE'], CONFIG['PRICE_HISTORY_FILE'])
    print(f"🧹 Reset paper trading files for {session_date.isoformat()}")


def load_paper_session_files(session_date):
    trades = []
    price_history = []

    if os.path.exists(CONFIG['PAPER_OUTPUT_FILE']):
        try:
            trades_df = pd.read_csv(CONFIG['PAPER_OUTPUT_FILE'])
            if not trades_df.empty and "Entry_Time" in trades_df.columns:
                entry_dates = pd.to_datetime(trades_df["Entry_Time"], errors="coerce").dt.date
                trades_df = trades_df.loc[entry_dates == session_date]
            trades = trades_df.to_dict("records") if not trades_df.empty else []
        except Exception as exc:
            print(f"⚠️ Could not reload paper trades: {exc}")

    if os.path.exists(CONFIG['PRICE_HISTORY_FILE']):
        try:
            price_df = pd.read_csv(CONFIG['PRICE_HISTORY_FILE'])
            if not price_df.empty and "DateTime" in price_df.columns:
                price_dates = pd.to_datetime(price_df["DateTime"], errors="coerce").dt.date
                price_df = price_df.loc[price_dates == session_date]
            price_history = price_df.to_dict("records") if not price_df.empty else []
        except Exception as exc:
            print(f"⚠️ Could not reload price history: {exc}")

    return trades, price_history


def has_paper_session_data(session_date):
    trades, price_history = load_paper_session_files(session_date)
    return bool(trades or price_history), trades, price_history


def persist_paper_session_snapshot(trades, price_history):
    save_trade_and_price_files(trades, price_history, CONFIG['PAPER_OUTPUT_FILE'], CONFIG['PRICE_HISTORY_FILE'])


def run_paper_trading():
    """Forward-test paper trading using Angel market data with no real-money orders."""
    print("🧪 Starting PAPER TRADING MODE (Angel market data, no real money)")
    print(f"📡 Forward testing {CONFIG['MARKET_DATA_SYMBOL']} via Angel One")

    try:
        smart_api = create_angel_session()
    except Exception as e:
        print(f"❌ {e}")
        return

    print("✅ Angel One login successful")
    trading_profile = resolve_trading_profile()
    strategy_name = trading_profile.strategy_name
    print(f"🧠 Active forward profile: {trading_profile.describe()} [{trading_profile.source}]")
    trades = []
    price_history = []
    in_position = False
    pos_type, entry_price, entry_time = "", 0.0, None
    entry_data = {}
    quantity = 0
    stop_loss_price = None
    target_price = None
    last_candle_time = None
    session_date = None
    daily_pnl = 0.0
    peak_daily_pnl = 0.0
    daily_trading_paused = False
    pause_reason = ""

    try:
        while True:
            now = datetime.now()
            if now.weekday() < 5 and session_date != now.date():
                session_date = now.date()
                has_existing_session, restored_trades, restored_price_history = has_paper_session_data(session_date)
                if has_existing_session:
                    trades = restored_trades
                    price_history = restored_price_history
                    daily_pnl = sum(safe_float(trade.get("Net_PnL", 0.0)) for trade in trades)
                    peak_daily_pnl = max(daily_pnl, 0.0)
                    print(f"♻️ Restored paper session for {session_date.isoformat()} | Trades: {len(trades)} | Price rows: {len(price_history)}")
                else:
                    reset_paper_session_files(session_date)
                    trades = []
                    price_history = []
                    daily_pnl = 0.0
                    peak_daily_pnl = 0.0
                daily_trading_paused = False
                pause_reason = ""
            market_open, market_close = get_market_window(now)

            if now >= market_close:
                print("🏁 Market closed. Sending final report...")
                if in_position:
                    current_price = get_live_price(
                        smart_api,
                        CONFIG["MARKET_DATA_SYMBOL"],
                        CONFIG["MARKET_DATA_EXCHANGE"],
                        CONFIG["MARKET_DATA_SYMBOL_TOKEN"],
                    )
                    if current_price is not None:
                        params = risk_management()
                        exit_price = current_price * (1 - (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                        points, net_pnl = calculate_trade_pnl(entry_price, exit_price, pos_type, quantity or CONFIG["LOT_SIZE"], entry_data.get("brokerage_fee", params['brokerage_fee']))
                        trades.append({
                            "Trade_ID": f"PAPER_{len(trades)+1}",
                            "Entry_Time": entry_time,
                            "Exit_Time": now,
                            "Type": pos_type,
                            "Qty": quantity or CONFIG["LOT_SIZE"],
                            "Entry_Price": round(entry_price, 2),
                            "Exit_Price": round(exit_price, 2),
                            "Points": round(points, 2),
                            "Net_PnL": round(net_pnl, 2),
                            "Exit_Reason": "MARKET_CLOSE",
                            "Entry_RSI": entry_data.get('rsi'),
                            "Entry_EMA_F": entry_data.get('ema_f'),
                            "Exit_RSI": None,
                            "Entry_Score": entry_data.get("entry_score"),
                            "Strategy": strategy_name
                        })
                        print(f"🔴 Paper exit simulated: {pos_type} closed at {exit_price:.2f} @ {now:%Y-%m-%d %H:%M} | PnL: ₹{net_pnl:.2f} (MARKET_CLOSE)")
                finalize_trading_session(trades, price_history, CONFIG['PAPER_OUTPUT_FILE'], CONFIG['PRICE_HISTORY_FILE'], "PAPER TRADING")
                send_session_email()
                print("✅ Paper trading session complete. Exiting...")
                return

            if now < market_open or now.weekday() >= 5:
                print(f"⏰ Outside market hours ({now.strftime('%H:%M')}). Waiting...")
                time.sleep(60)
                continue

            try:
                df = fetch_angel_candles(
                    smart_api,
                    CONFIG["MARKET_DATA_EXCHANGE"],
                    CONFIG["MARKET_DATA_SYMBOL_TOKEN"],
                    CONFIG["MARKET_DATA_INTERVAL"],
                    now - timedelta(days=CONFIG["CANDLE_LOOKBACK_DAYS"]),
                    now,
                )
                if df.empty or len(df) < MIN_SIGNAL_CANDLES:
                    print("⏳ Waiting for enough Angel candle history...")
                    time.sleep(CONFIG["MARKET_POLL_SECONDS"])
                    continue

                current_time = df.index[-1].to_pydatetime()
                if current_time.date() != now.date():
                    print("⏳ Waiting for today's first Angel candle...")
                    time.sleep(CONFIG["MARKET_POLL_SECONDS"])
                    continue

                current_price = get_live_price(
                    smart_api,
                    CONFIG["MARKET_DATA_SYMBOL"],
                    CONFIG["MARKET_DATA_EXCHANGE"],
                    CONFIG["MARKET_DATA_SYMBOL_TOKEN"],
                )
                if current_price is None:
                    current_price = float(df['Close'].iloc[-1])

                params = risk_management()
                recent_candles = get_recent_candles_from_market_df(df, lookback=60)
                price_window = recent_candles['Close'].tolist()
                signal_data = calculate_signals(
                    price_list=price_window,
                    current_time=current_time,
                    position=(1 if pos_type == "LONG" else -1) if in_position else 0,
                    entry_price=entry_price,
                    strategy_name=strategy_name,
                    candles_df=recent_candles,
                    capital=CONFIG["CAPITAL"],
                    lot_size=CONFIG["LOT_SIZE"],
                )
                action = signal_data.get('action', 'WAIT')
                is_new_candle = current_time != last_candle_time
                peak_daily_pnl = max(peak_daily_pnl, daily_pnl)
                daily_trading_paused, pause_reason = should_pause_new_entries(daily_pnl, peak_daily_pnl)

                if in_position:
                    stop_loss_price = update_trailing_stop(current_price, entry_price, pos_type, stop_loss_price, entry_data)

                if is_new_candle:
                    candle = df.iloc[-1]
                    price_history.append({
                        "DateTime": current_time,
                        "Price": current_price,
                        "High": float(candle['High']),
                        "Low": float(candle['Low']),
                        "Volume": float(candle['Volume']) if 'Volume' in candle.index else 0,
                        "Signal": action,
                        "RSI": signal_data.get('rsi'),
                        "RSI_FAST": signal_data.get('rsi_fast'),
                        "EMA_FAST": signal_data.get('ema_f'),
                        "SLOPE": signal_data.get('slope'),
                        "PERCENT_B": signal_data.get('percent_b') if 'percent_b' in signal_data else None,
                        "ATR": signal_data.get("atr"),
                        "Volume_Ratio": signal_data.get("volume_ratio"),
                        "Entry_Score": signal_data.get("entry_score"),
                        "REGIME": signal_data.get('regime'),
                        "Strategy": strategy_name,
                        "Stop_Loss": stop_loss_price,
                        "Target": target_price
                    })
                    last_candle_time = current_time
                    persist_paper_session_snapshot(trades, price_history)

                exit_reason = None
                if in_position:
                    if stop_loss_price is not None and ((pos_type == "LONG" and current_price <= stop_loss_price) or (pos_type == "SHORT" and current_price >= stop_loss_price)):
                        exit_reason = "EXIT_SL"
                    elif target_price is not None and ((pos_type == "LONG" and current_price >= target_price) or (pos_type == "SHORT" and current_price <= target_price)):
                        exit_reason = "EXIT_TARGET"
                    elif is_new_candle and action.startswith("EXIT"):
                        exit_reason = action

                if not in_position and is_new_candle and action in ["BUY_LONG", "SELL_SHORT"] and not daily_trading_paused and trading_profile.permits_entry(action, current_time):
                    pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
                    quantity = int(signal_data.get("suggested_qty", CONFIG["LOT_SIZE"]))
                    entry_price = current_price * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                    entry_time = now
                    entry_data = signal_data
                    stop_loss_price, target_price = calculate_entry_levels(entry_price, pos_type, signal_data)
                    risk_budget = get_new_entry_risk_budget(daily_pnl, peak_daily_pnl)
                    risk_allowed, planned_risk = is_trade_risk_allowed(entry_price, stop_loss_price, quantity, signal_data.get("brokerage_fee", params["brokerage_fee"]), risk_budget)
                    if not risk_allowed:
                        print(f"🛡️ Skipping paper entry: planned risk ₹{planned_risk:.2f} exceeds allowed risk ₹{risk_budget:.2f}")
                        pos_type = ""
                        entry_price = 0.0
                        entry_time = None
                        entry_data = {}
                        quantity = 0
                        stop_loss_price = None
                        target_price = None
                        time.sleep(CONFIG["MARKET_POLL_SECONDS"])
                        continue
                    entry_data["planned_risk"] = planned_risk
                    in_position = True
                    print(f"🟢 Paper entry simulated: {pos_type} at {entry_price:.2f} | Qty {quantity} | SL {stop_loss_price:.2f} | Target {target_price:.2f}")
                    time.sleep(CONFIG["MARKET_POLL_SECONDS"])
                    continue

                if in_position and exit_reason is not None:
                    exit_price = current_price * (1 - (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                    points, net_pnl = calculate_trade_pnl(entry_price, exit_price, pos_type, quantity or CONFIG["LOT_SIZE"], entry_data.get("brokerage_fee", params['brokerage_fee']))
                    daily_pnl += net_pnl
                    peak_daily_pnl = max(peak_daily_pnl, daily_pnl)
                    trades.append({
                        "Trade_ID": f"PAPER_{len(trades)+1}",
                        "Entry_Time": entry_time,
                        "Exit_Time": now,
                        "Type": pos_type,
                        "Qty": quantity or CONFIG["LOT_SIZE"],
                        "Entry_Price": round(entry_price, 2),
                        "Exit_Price": round(exit_price, 2),
                        "Points": round(points, 2),
                        "Net_PnL": round(net_pnl, 2),
                        "Exit_Reason": exit_reason,
                        "Entry_RSI": entry_data.get('rsi'),
                        "Entry_EMA_F": entry_data.get('ema_f'),
                        "Exit_RSI": signal_data.get('rsi'),
                        "Entry_Score": entry_data.get("entry_score"),
                        "Strategy": strategy_name,
                        "Planned_Risk": round(entry_data.get("planned_risk", 0.0), 2),
                        "Daily_PnL_After": round(daily_pnl, 2),
                        "Risk_Allowed": True,
                        "Session_Stop": pause_reason,
                    })
                    print(f"🔴 Paper exit simulated: {pos_type} closed at {exit_price:.2f} @ {now:%Y-%m-%d %H:%M} | PnL: ₹{net_pnl:.2f} ({exit_reason})")
                    persist_paper_session_snapshot(trades, price_history)
                    in_position = False
                    pos_type = ""
                    entry_price = 0.0
                    entry_time = None
                    entry_data = {}
                    quantity = 0
                    stop_loss_price = None
                    target_price = None

                time.sleep(CONFIG["MARKET_POLL_SECONDS"])
            except Exception as e:
                print(f"❌ Paper trading error: {e}")
                time.sleep(60)
    finally:
        close_angel_session(smart_api)


def run_angel_backtest():
    end_dt = datetime.now()
    requested_start_dt = end_dt - timedelta(days=180)
    intraday_start_dt = max(requested_start_dt, end_dt - timedelta(days=55))
    if intraday_start_dt > requested_start_dt:
        print("ℹ️  Yahoo 5-minute data is limited to about the last 60 days. Falling back to the latest 55 days.")
    start_dt = intraday_start_dt
    print(f"📡 Fetching data for {CONFIG['SYMBOL']} from {start_dt.strftime('%Y-%m-%d')}...")
    df = fetch_backtest_market_data(CONFIG['SYMBOL'], start_dt, end_dt, interval="5m")
    
    if df.empty:
        print("❌ Data is empty")
        return

    df = df.dropna()
    if len(df) < MIN_SIGNAL_CANDLES:
        print(f"❌ Insufficient data: {len(df)} < {MIN_SIGNAL_CANDLES} required")
        return

    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    data_records = df.reset_index().to_dict('records')

    print(f"\n📊 Running execution-aligned profile backtests on {len(data_records)} candles...")

    configured_profile = build_default_trading_profile()
    adaptive_profile = resolve_trading_profile()

    configured_results = run_profile_backtest(data_records, configured_profile)
    adaptive_results = run_profile_backtest(data_records, adaptive_profile)

    profile_results = [
        ("CONFIGURED_PROFILE", configured_results),
    ]
    if adaptive_profile != configured_profile:
        profile_results.append(("ADAPTIVE_PROFILE", adaptive_results))

    for label, results in profile_results:
        profile = results["profile"]
        stats = results["stats"]
        print(
            f"  {label}: {profile.describe()} | "
            f"{results['trades']} trades | Total PnL: ₹{results['total_pnl']:,.2f} | "
            f"Win Rate: {results['win_rate']:.1f}% | "
            f"Profit Factor: {stats['profit_factor']} | Max DD: ₹{stats['max_drawdown']:,.2f}"
        )
        output_file = f"{label.lower()}_backtest_results.csv"
        results["df"].to_csv(output_file, index=False)

    adaptive_results["price_history_df"].to_csv(CONFIG["PRICE_HISTORY_FILE"], index=False)

    print("\n📊 Diagnostic unrestricted strategy comparison:")
    all_strategies_results = {}
    best_strategy = None
    best_pnl = -float("inf")

    for strategy_name in ["strategy_1", "strategy_2", "strategy_3", "strategy_4"]:
        unrestricted_profile = TradingProfile(strategy_name=strategy_name, source="backtest")
        results = run_profile_backtest(data_records, unrestricted_profile)
        all_strategies_results[strategy_name] = results

        if results["trades"] > 0:
            stats = results["stats"]
            print(
                f"  {strategy_name.upper()}: {results['trades']} trades | "
                f"Total PnL: ₹{results['total_pnl']:,.2f} | Win Rate: {results['win_rate']:.1f}% | "
                f"Profit Factor: {stats['profit_factor']} | Max DD: ₹{stats['max_drawdown']:,.2f}"
            )
            if results["total_pnl"] > best_pnl:
                best_pnl = results["total_pnl"]
                best_strategy = strategy_name
        else:
            print(f"  {strategy_name.upper()}: No trades generated")

        results["df"].to_csv(f"{strategy_name}_backtest_results.csv", index=False)

    if best_strategy is not None:
        print(f"\n🏆 BEST UNRESTRICTED STRATEGY: {best_strategy.upper()} with ₹{best_pnl:,.2f} PnL")

if __name__ == "__main__":
    if CONFIG['LIVE_MODE']:
        print("⚠️  LIVE_MODE is enabled, but this build stays in Angel-powered paper mode by default for safety.")
        run_paper_trading()
    elif CONFIG['PAPER_MODE']:
        run_paper_trading()
    else:
        run_angel_backtest()

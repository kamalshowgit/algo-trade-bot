import pandas as pd
import numpy as np
import yfinance as yf
import os
import time
from datetime import datetime, timedelta, time as dt_time
from engine import STRATEGIES, calculate_signals, risk_management
from dotenv import load_dotenv

load_dotenv()

def get_int_env(name, default, minimum=None):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


CONFIG = {
    "SYMBOL": "^NSEI",
    "LOT_SIZE": 50,
    "CAPITAL": 100000,
    "SLIPPAGE_BPS": 0.0004,
    "OUTPUT_FILE": "angel_backtest_results.csv",
    "PAPER_OUTPUT_FILE": os.getenv("PAPER_OUTPUT_FILE", "paper_trade_history.csv"),
    "PRICE_HISTORY_FILE": os.getenv("PRICE_HISTORY_FILE", "price_history.csv"),
    "LIVE_MODE": os.getenv("LIVE_MODE", "False").lower() == "true",
    "PAPER_MODE": os.getenv("PAPER_MODE", "True").lower() == "true",
    "MARKET_DATA_EXCHANGE": os.getenv("MARKET_DATA_EXCHANGE", "NSE"),
    "MARKET_DATA_SYMBOL": os.getenv("MARKET_DATA_SYMBOL", "NIFTY"),
    "MARKET_DATA_SYMBOL_TOKEN": os.getenv("MARKET_DATA_SYMBOL_TOKEN", "99926000"),
    "MARKET_DATA_INTERVAL": os.getenv("MARKET_DATA_INTERVAL", "FIVE_MINUTE"),
    "MARKET_POLL_SECONDS": get_int_env("MARKET_POLL_SECONDS", 30, minimum=5),
    "CANDLE_LOOKBACK_DAYS": get_int_env("CANDLE_LOOKBACK_DAYS", 2, minimum=1),
    "TRADE_EXCHANGE": os.getenv("TRADE_EXCHANGE", "NSE"),
    "TRADE_SYMBOL": os.getenv("TRADE_SYMBOL", "NIFTY30APR26FUT"),
    "TRADE_SYMBOL_TOKEN": os.getenv("TRADE_SYMBOL_TOKEN", "99926000"),
    "FORWARD_STRATEGY": os.getenv("FORWARD_STRATEGY", "strategy_1").strip().lower()
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
    "Entry_Price",
    "Exit_Price",
    "Points",
    "Net_PnL",
    "Exit_Reason",
    "Entry_RSI",
    "Entry_EMA_F",
    "Exit_RSI",
    "Strategy",
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


def run_live_trading():
    """Run live trading during market hours and exit after market close."""
    print("🚀 Starting LIVE TRADING MODE")

    try:
        smart_api = create_angel_session()
    except Exception as e:
        print(f"❌ {e}")
        return

    print("✅ Angel One login successful")
    print(f"📡 Using Angel market data for {CONFIG['MARKET_DATA_SYMBOL']} ({CONFIG['MARKET_DATA_INTERVAL']})")
    strategy_name = get_forward_strategy_name()
    print(f"🧠 Active forward strategy: {strategy_name}")

    trades = []
    price_history = []
    in_position = False
    pos_type, entry_price, entry_time = "", 0.0, None
    entry_data = {}
    stop_loss_price = None
    target_price = None
    last_candle_time = None

    try:
        while True:
            now = datetime.now()
            market_open, market_close = get_market_window(now)

            if now >= market_close:
                print("🏁 Market closed. Sending final report...")
                if in_position:
                    current_price = get_live_price(
                        smart_api,
                        CONFIG["TRADE_SYMBOL"],
                        CONFIG["TRADE_EXCHANGE"],
                        CONFIG["TRADE_SYMBOL_TOKEN"],
                    )
                    if current_price is not None:
                        exit_price = calculate_exit_price(current_price, pos_type == "LONG", CONFIG['SLIPPAGE_BPS'])
                        points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                        net_pnl = (points * CONFIG['LOT_SIZE']) - risk_management()['brokerage_fee']
                        trades.append({
                            "Trade_ID": f"ANGEL_{len(trades)+1}",
                            "Entry_Time": entry_time,
                            "Exit_Time": now,
                            "Type": pos_type,
                            "Entry_Price": round(entry_price, 2),
                            "Exit_Price": round(exit_price, 2),
                            "Points": round(points, 2),
                            "Net_PnL": round(net_pnl, 2),
                            "Exit_Reason": "MARKET_CLOSE",
                            "Entry_RSI": entry_data.get('rsi'),
                            "Entry_EMA_F": entry_data.get('ema_f'),
                            "Exit_RSI": None,
                            "Strategy": strategy_name
                        })
                finalize_trading_session(trades, price_history, CONFIG['OUTPUT_FILE'], CONFIG['PRICE_HISTORY_FILE'], "LIVE TRADING")
                send_session_email()
                print("✅ Live trading session complete. Exiting...")
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
                if df.empty or len(df) < 26:
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

                price_window = df['Close'].tail(26).tolist()
                risk = risk_management()
                position_flag = 1 if pos_type == "LONG" else -1 if pos_type == "SHORT" else 0
                signal_data = calculate_signals(
                    price_list=price_window,
                    current_time=current_time,
                    position=position_flag,
                    entry_price=entry_price,
                    strategy_name=strategy_name
                )
                action = signal_data.get('action', 'WAIT')
                is_new_candle = current_time != last_candle_time

                if in_position:
                    pnl_pct = ((current_price - entry_price) / entry_price) if pos_type == "LONG" else ((entry_price - current_price) / entry_price)
                    if pnl_pct >= risk['breakeven_pct']:
                        if pos_type == "LONG":
                            stop_loss_price = max(stop_loss_price or entry_price, entry_price)
                            trail_price = entry_price * (1 + risk['trail_distance'])
                            stop_loss_price = max(stop_loss_price, trail_price)
                        else:
                            stop_loss_price = min(stop_loss_price or entry_price, entry_price)
                            trail_price = entry_price * (1 - risk['trail_distance'])
                            stop_loss_price = min(stop_loss_price, trail_price)

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
                        points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                        net_pnl = (points * CONFIG['LOT_SIZE']) - risk['brokerage_fee']
                        trades.append({
                            "Trade_ID": f"ANGEL_{len(trades)+1}",
                            "Entry_Time": entry_time,
                            "Exit_Time": now,
                            "Type": pos_type,
                            "Entry_Price": round(entry_price, 2),
                            "Exit_Price": round(exit_price, 2),
                            "Points": round(points, 2),
                            "Net_PnL": round(net_pnl, 2),
                            "Exit_Reason": exit_reason,
                            "Entry_RSI": entry_data.get('rsi'),
                            "Entry_EMA_F": entry_data.get('ema_f'),
                            "Exit_RSI": signal_data.get('rsi'),
                            "Strategy": strategy_name
                        })

                        exit_side = "SELL" if pos_type == "LONG" else "BUY"
                        exit_order = place_order(
                            smart_api,
                            CONFIG["TRADE_SYMBOL"],
                            exit_side,
                            CONFIG['LOT_SIZE'],
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
                        "REGIME": signal_data.get('regime'),
                        "Strategy": strategy_name,
                        "Stop_Loss": stop_loss_price,
                        "Target": target_price
                    })
                    last_candle_time = current_time

                if not in_position and is_new_candle and action in ["BUY_LONG", "SELL_SHORT"]:
                    pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
                    entry_price = current_price * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                    entry_time = now
                    entry_data = signal_data
                    stop_loss_price = entry_price * (1 - risk['stop_loss_pct']) if pos_type == "LONG" else entry_price * (1 + risk['stop_loss_pct'])
                    target_price = entry_price * (1 + risk['target_pct_3']) if pos_type == "LONG" else entry_price * (1 - risk['target_pct_3'])
                    side = "BUY" if pos_type == "LONG" else "SELL"
                    order_response = place_order(
                        smart_api,
                        CONFIG["TRADE_SYMBOL"],
                        side,
                        CONFIG['LOT_SIZE'],
                        entry_price,
                        exchange=CONFIG["TRADE_EXCHANGE"],
                        symbol_token=CONFIG["TRADE_SYMBOL_TOKEN"],
                    )
                    if order_response:
                        in_position = True
                        print(f"✅ Entered {pos_type} on {CONFIG['TRADE_SYMBOL']} at {entry_price:.2f} | SL {stop_loss_price:.2f} | Target {target_price:.2f}")
                    else:
                        print("❌ Live entry failed. Waiting for next signal.")
                        pos_type = ""
                        entry_price = 0.0
                        entry_time = None
                        entry_data = {}
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
    strategy_name = get_forward_strategy_name()
    print(f"🧠 Active forward strategy: {strategy_name}")
    trades = []
    price_history = []
    in_position = False
    pos_type, entry_price, entry_time = "", 0.0, None
    entry_data = {}
    stop_loss_price = None
    target_price = None
    last_candle_time = None
    session_date = None

    try:
        while True:
            now = datetime.now()
            if now.weekday() < 5 and session_date != now.date():
                reset_paper_session_files(now.date())
                session_date = now.date()
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
                        points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                        net_pnl = (points * CONFIG['LOT_SIZE']) - params['brokerage_fee']
                        trades.append({
                            "Trade_ID": f"PAPER_{len(trades)+1}",
                            "Entry_Time": entry_time,
                            "Exit_Time": now,
                            "Type": pos_type,
                            "Entry_Price": round(entry_price, 2),
                            "Exit_Price": round(exit_price, 2),
                            "Points": round(points, 2),
                            "Net_PnL": round(net_pnl, 2),
                            "Exit_Reason": "MARKET_CLOSE",
                            "Entry_RSI": entry_data.get('rsi'),
                            "Entry_EMA_F": entry_data.get('ema_f'),
                            "Exit_RSI": None,
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
                if df.empty or len(df) < 26:
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
                price_window = df['Close'].tail(26).tolist()
                signal_data = calculate_signals(
                    price_list=price_window,
                    current_time=current_time,
                    position=(1 if pos_type == "LONG" else -1) if in_position else 0,
                    entry_price=entry_price,
                    strategy_name=strategy_name
                )
                action = signal_data.get('action', 'WAIT')
                is_new_candle = current_time != last_candle_time

                if in_position:
                    pnl_pct = ((current_price - entry_price) / entry_price) if pos_type == "LONG" else ((entry_price - current_price) / entry_price)
                    if pnl_pct >= params['breakeven_pct']:
                        if pos_type == "LONG":
                            stop_loss_price = max(stop_loss_price or entry_price, entry_price)
                            stop_loss_price = max(stop_loss_price, entry_price * (1 + params['trail_distance']))
                        else:
                            stop_loss_price = min(stop_loss_price or entry_price, entry_price)
                            stop_loss_price = min(stop_loss_price, entry_price * (1 - params['trail_distance']))

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

                if not in_position and is_new_candle and action in ["BUY_LONG", "SELL_SHORT"]:
                    pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
                    entry_price = current_price * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                    entry_time = now
                    entry_data = signal_data
                    stop_loss_price = entry_price * (1 - params['stop_loss_pct']) if pos_type == "LONG" else entry_price * (1 + params['stop_loss_pct'])
                    target_price = entry_price * (1 + params['target_pct_3']) if pos_type == "LONG" else entry_price * (1 - params['target_pct_3'])
                    in_position = True
                    print(f"🟢 Paper entry simulated: {pos_type} at {entry_price:.2f} | SL {stop_loss_price:.2f} | Target {target_price:.2f}")
                    time.sleep(CONFIG["MARKET_POLL_SECONDS"])
                    continue

                if in_position and exit_reason is not None:
                    exit_price = current_price * (1 - (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                    points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                    net_pnl = (points * CONFIG['LOT_SIZE']) - params['brokerage_fee']
                    trades.append({
                        "Trade_ID": f"PAPER_{len(trades)+1}",
                        "Entry_Time": entry_time,
                        "Exit_Time": now,
                        "Type": pos_type,
                        "Entry_Price": round(entry_price, 2),
                        "Exit_Price": round(exit_price, 2),
                        "Points": round(points, 2),
                        "Net_PnL": round(net_pnl, 2),
                        "Exit_Reason": exit_reason,
                        "Entry_RSI": entry_data.get('rsi'),
                        "Entry_EMA_F": entry_data.get('ema_f'),
                        "Exit_RSI": signal_data.get('rsi'),
                        "Strategy": strategy_name
                    })
                    print(f"🔴 Paper exit simulated: {pos_type} closed at {exit_price:.2f} @ {now:%Y-%m-%d %H:%M} | PnL: ₹{net_pnl:.2f} ({exit_reason})")
                    persist_paper_session_snapshot(trades, price_history)
                    in_position = False
                    pos_type = ""
                    entry_price = 0.0
                    entry_time = None
                    entry_data = {}
                    stop_loss_price = None
                    target_price = None

                time.sleep(CONFIG["MARKET_POLL_SECONDS"])
            except Exception as e:
                print(f"❌ Paper trading error: {e}")
                time.sleep(60)
    finally:
        close_angel_session(smart_api)


def run_angel_backtest():
    start_date = (datetime.now() - timedelta(days=58)).strftime('%Y-%m-%d')
    print(f"📡 Fetching data for {CONFIG['SYMBOL']} from {start_date}...")
    df = yf.download(CONFIG['SYMBOL'], start=start_date, interval="5m")
    
    if df.empty:
        print("❌ Data is empty")
        return

    df = df.dropna()
    if len(df) < 30:
        print(f"❌ Insufficient data: {len(df)} < 30 required")
        return

    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    data_records = df.reset_index().to_dict('records')
    
    print(f"\n📊 Running backtests with 4 strategies on {len(data_records)} candles...")
    
    all_strategies_results = {}
    best_strategy = None
    best_pnl = -float('inf')
    
    strategies = ["strategy_1", "strategy_2", "strategy_3", "strategy_4"]
    
    for strategy_name in strategies:
        trades = []
        price_history = []
        in_position = False
        pos_type, entry_price, entry_time = "", 0.0, None
        daily_pnl, current_day = 0, None
        entry_data = {}
        stop_loss_price = None
        target_price = None

        for i in range(30, len(data_records)):
            params = risk_management()
            row = data_records[i]
            now_time, now_close = row['Datetime'], float(row['Close'])
            
            price_history.append({
                "DateTime": now_time,
                "Price": now_close,
                "High": float(row['High']),
                "Low": float(row['Low']),
                "Volume": float(row['Volume']) if 'Volume' in row else 0
            })
            
            if current_day != now_time.date():
                if in_position and i > 0:
                    trades.append({
                        "Trade_ID": f"{strategy_name.upper()}_{len(trades)+1}", 
                        "Entry_Time": entry_time, 
                        "Exit_Time": data_records[i-1]['Datetime'],
                        "Type": pos_type, 
                        "Entry_Price": round(entry_price, 2), 
                        "Exit_Price": round(data_records[i-1]['Close'], 2),
                        "Net_PnL": round(((data_records[i-1]['Close'] - entry_price) if pos_type == "LONG" else (entry_price - data_records[i-1]['Close'])) * CONFIG['LOT_SIZE'] - params['brokerage_fee'], 2),
                        "Exit_Reason": "GAP_PROTECTION", 
                        "Entry_RSI": entry_data.get('rsi'), 
                        "Entry_EMA_F": entry_data.get('ema_f'),
                        "Strategy": strategy_name
                    })
                    in_position = False
                current_day, daily_pnl = now_time.date(), 0

            price_window = [r['Close'] for r in data_records[max(0, i-25):i+1]]
            signal_data = calculate_signals(
                price_list=price_window, 
                current_time=now_time, 
                position=(1 if pos_type == "LONG" else -1) if in_position else 0, 
                entry_price=entry_price,
                strategy_name=strategy_name
            )
            
            action = signal_data.get('action', 'WAIT')

            if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:
                in_position = True
                pos_type = "LONG" if "BUY" in action else "SHORT"
                entry_price = now_close * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                entry_time = now_time
                entry_data = signal_data
                stop_loss_price = entry_price * (1 - params['stop_loss_pct']) if pos_type == "LONG" else entry_price * (1 + params['stop_loss_pct'])
                target_price = entry_price * (1 + params['target_pct_3']) if pos_type == "LONG" else entry_price * (1 - params['target_pct_3'])
            
            elif in_position:
                pnl_pct = ((now_close - entry_price) / entry_price) if pos_type == "LONG" else ((entry_price - now_close) / entry_price)
                if pnl_pct >= params['breakeven_pct']:
                    if pos_type == "LONG":
                        stop_loss_price = max(stop_loss_price or entry_price, entry_price)
                        stop_loss_price = max(stop_loss_price, entry_price * (1 + params['trail_distance']))
                    else:
                        stop_loss_price = min(stop_loss_price or entry_price, entry_price)
                        stop_loss_price = min(stop_loss_price, entry_price * (1 - params['trail_distance']))

                exit_reason = None
                if stop_loss_price is not None and ((pos_type == "LONG" and now_close <= stop_loss_price) or (pos_type == "SHORT" and now_close >= stop_loss_price)):
                    exit_reason = "EXIT_SL"
                elif target_price is not None and ((pos_type == "LONG" and now_close >= target_price) or (pos_type == "SHORT" and now_close <= target_price)):
                    exit_reason = "EXIT_TARGET"
                elif action.startswith("EXIT"):
                    exit_reason = action

                if exit_reason is not None:
                    exit_price = now_close * (1 - (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                    points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                    net_pnl = (points * CONFIG['LOT_SIZE']) - params['brokerage_fee']
                    daily_pnl += net_pnl
                    
                    trades.append({
                        "Trade_ID": f"{strategy_name.upper()}_{len(trades)+1}",
                        "Entry_Time": entry_time,
                        "Exit_Time": now_time,
                        "Type": pos_type,
                        "Entry_Price": round(entry_price, 2),
                        "Exit_Price": round(exit_price, 2),
                        "Points": round(points, 2),
                        "Net_PnL": round(net_pnl, 2),
                        "Exit_Reason": exit_reason,
                        "Entry_RSI": entry_data.get('rsi'),
                        "Entry_EMA_F": entry_data.get('ema_f'),
                        "Exit_RSI": signal_data.get('rsi'),
                        "Strategy": strategy_name
                    })
                    in_position = False

        if trades:
            report_df = pd.DataFrame(trades)
            total_pnl = report_df['Net_PnL'].sum()
            win_rate = (report_df['Net_PnL'] > 0).sum() / len(report_df) * 100
            
            all_strategies_results[strategy_name] = {
                "df": report_df,
                "total_pnl": total_pnl,
                "trades": len(report_df),
                "win_rate": win_rate,
                "avg_pnl": report_df['Net_PnL'].mean()
            }
            
            print(f"  {strategy_name.upper()}: {len(report_df)} trades | Total PnL: ₹{total_pnl:,.2f} | Win Rate: {win_rate:.1f}%")
            
            if total_pnl > best_pnl:
                best_pnl = total_pnl
                best_strategy = strategy_name
        else:
            print(f"  {strategy_name.upper()}: No trades generated")
            all_strategies_results[strategy_name] = {"df": None, "total_pnl": 0, "trades": 0, "win_rate": 0, "avg_pnl": 0}

    # Save results for all strategies
    for strategy_name, results in all_strategies_results.items():
        if results["df"] is not None:
            output_file = f"{strategy_name}_backtest_results.csv"
            results["df"].to_csv(output_file, index=False)
    
    # Save price history (same for all strategies)
    price_history_df = pd.DataFrame(price_history)
    price_history_df.to_csv(CONFIG['PRICE_HISTORY_FILE'], index=False)
    
    print(f"\n🏆 BEST STRATEGY: {best_strategy.upper()} with ₹{best_pnl:,.2f} PnL")
    print(f"   📊 View individual results:")
    for strategy_name, results in all_strategies_results.items():
        if results["trades"] > 0:
            print(f"      - {strategy_name.upper()}: {results['trades']} trades, ₹{results['total_pnl']:,.2f} PnL, {results['win_rate']:.1f}% win rate")

if __name__ == "__main__":
    if CONFIG['LIVE_MODE']:
        print("⚠️  LIVE_MODE is enabled, but this build stays in Angel-powered paper mode by default for safety.")
        run_paper_trading()
    elif CONFIG['PAPER_MODE']:
        run_paper_trading()
    else:
        run_angel_backtest()

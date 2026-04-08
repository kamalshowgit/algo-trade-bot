import pandas as pd
import numpy as np
import yfinance as yf
import os
import time
from datetime import datetime, timedelta
from engine import calculate_signals, risk_management
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    "SYMBOL": "^NSEI",
    "LOT_SIZE": 50,
    "CAPITAL": 100000,
    "SLIPPAGE_BPS": 0.0004,
    "OUTPUT_FILE": "angel_backtest_results.csv",
    "PAPER_OUTPUT_FILE": os.getenv("PAPER_OUTPUT_FILE", "paper_trade_history.csv"),
    "PRICE_HISTORY_FILE": os.getenv("PRICE_HISTORY_FILE", "price_history.csv"),
    "LIVE_MODE": os.getenv("LIVE_MODE", "False").lower() == "true",
    "PAPER_MODE": os.getenv("PAPER_MODE", "True").lower() == "true"
}

# Angel One credentials
API_KEY = os.getenv("ANGEL_API_KEY")
CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
PASSWORD = os.getenv("ANGEL_PASSWORD")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

def place_order(smart_api, symbol, side, quantity, price):
    """Place an order via Angel One API."""
    try:
        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": symbol,
            "symboltoken": "99926000",  # NSE NIFTY token
            "transactiontype": side,
            "exchange": "NSE",
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


def get_live_price(smart_api, symbol):
    """Try Angel One live quote first, fallback to yfinance if needed."""
    try:
        if hasattr(smart_api, "getLTP"):
            quote = smart_api.getLTP("NSE", symbol)
            if isinstance(quote, dict):
                return float(quote.get("ltp", 0) or 0)
        if hasattr(smart_api, "get_quotes"):
            quote = smart_api.get_quotes("NSE", [symbol])
            if isinstance(quote, dict):
                return float(quote.get(symbol, {}).get("ltp", 0) or 0)
    except Exception:
        pass

    try:
        df = yf.download(symbol if symbol.startswith("^") else symbol, period="1d", interval="1m")
        if not df.empty:
            return float(df['Close'].iloc[-1])
    except Exception:
        pass
    return None


def calculate_exit_price(entry_price, is_long, slippage, short=False):
    if is_long:
        return entry_price * (1 - slippage)
    return entry_price * (1 + slippage)


def run_live_trading():
    """Run live trading during market hours and exit after market close."""
    print("🚀 Starting LIVE TRADING MODE")

    try:
        import pyotp
        from SmartApi import SmartConnect
    except ImportError as e:
        print(f"❌ Live trading dependencies not installed: {e}")
        return
    
    # Initialize API
    smart_api = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    login_response = smart_api.generateSession(CLIENT_ID, PASSWORD, totp)
    if not login_response.get('status'):
        print("❌ Angel One login failed")
        return
    
    print("✅ Angel One login successful")
    print("📡 Waiting for market open...")
    
    trades = []
    price_history = []
    in_position = False
    pos_type, entry_price, entry_time = "", 0.0, None
    entry_data = {}
    stop_loss_price = None
    target_price = None
    trade_symbol = "NIFTY30APR26FUT"
    
    while True:
        now = datetime.now()
        now_m = now.hour * 60 + now.minute
        
        if now_m >= 915:  # 3:15 PM IST
            print("🏁 Market closed. Sending final report...")
            if trades:
                report_df = pd.DataFrame(trades)
                report_df.to_csv(CONFIG['OUTPUT_FILE'], index=False)
                price_history_df = pd.DataFrame(price_history)
                price_history_df.to_csv(CONFIG['PRICE_HISTORY_FILE'], index=False)
                try:
                    from send_email_report import send_performance_email
                    send_performance_email()
                    print("✅ Email report sent")
                except Exception as e:
                    print(f"❌ Email failed: {e}")
            print("✅ Live trading session complete. Exiting...")
            return
        
        if not (555 <= now_m <= 915):
            print(f"⏰ Outside market hours ({now.strftime('%H:%M')}). Waiting...")
            time.sleep(60)
            continue

        try:
            end_time = now.replace(second=0, microsecond=0)
            start_time = end_time - timedelta(hours=1)
            df = yf.download(CONFIG['SYMBOL'], start=start_time, end=end_time, interval="5m")
            if df.empty or len(df) < 26:
                time.sleep(60)
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            current_price = get_live_price(smart_api, trade_symbol)
            if current_price is None:
                current_price = float(df['Close'].iloc[-1])
            current_time = df.index[-1].to_pydatetime()
            price_window = df['Close'].tail(26).tolist()
            if len(price_window) < 20:
                time.sleep(60)
                continue

            risk = risk_management()
            position_flag = 1 if pos_type == "LONG" else -1 if pos_type == "SHORT" else 0
            signal_data = calculate_signals(
                price_list=price_window,
                current_time=current_time,
                position=position_flag,
                entry_price=entry_price
            )
            action = signal_data.get('action', 'WAIT')

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
                if exit_reason is None and action.startswith("EXIT"):
                    exit_reason = action
                if exit_reason is None and target_price is not None:
                    if (pos_type == "LONG" and current_price >= target_price) or (pos_type == "SHORT" and current_price <= target_price):
                        exit_reason = "EXIT_TARGET"

                if exit_reason is not None:
                    exit_price = calculate_exit_price(current_price, pos_type == "LONG", CONFIG['SLIPPAGE_BPS'])
                    points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
                    net_pnl = (points * CONFIG['LOT_SIZE']) - risk['brokerage_fee']
                    trades.append({
                        "Trade_ID": f"ANGEL_{len(trades)+1}",
                        "Entry_Time": entry_time,
                        "Exit_Time": current_time,
                        "Type": pos_type,
                        "Entry_Price": round(entry_price, 2),
                        "Exit_Price": round(exit_price, 2),
                        "Points": round(points, 2),
                        "Net_PnL": round(net_pnl, 2),
                        "Exit_Reason": exit_reason,
                        "Entry_RSI": entry_data.get('rsi'),
                        "Entry_EMA_F": entry_data.get('ema_f'),
                        "Exit_RSI": signal_data.get('rsi')
                    })

                    exit_side = "SELL" if pos_type == "LONG" else "BUY"
                    exit_order = place_order(smart_api, trade_symbol, exit_side, CONFIG['LOT_SIZE'], exit_price)
                    if exit_order:
                        print(f"✅ Placed {exit_side} exit order for {trade_symbol} at {exit_price}")
                    else:
                        print(f"❌ Failed to place exit order for {trade_symbol} at {exit_price}")

                    in_position = False
                    pos_type = ""
                    entry_price = 0.0
                    entry_time = None
                    entry_data = {}
                    stop_loss_price = None
                    target_price = None

            if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:
                pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
                entry_price = current_price * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
                entry_time = current_time
                entry_data = signal_data
                stop_loss_price = entry_price * (1 - risk['stop_loss_pct']) if pos_type == "LONG" else entry_price * (1 + risk['stop_loss_pct'])
                target_price = entry_price * (1 + risk['target_pct_3']) if pos_type == "LONG" else entry_price * (1 - risk['target_pct_3'])
                side = "BUY" if pos_type == "LONG" else "SELL"
                order_response = place_order(smart_api, trade_symbol, side, CONFIG['LOT_SIZE'], entry_price)
                if order_response:
                    in_position = True
                    print(f"✅ Entered {pos_type} on {trade_symbol} at {entry_price} | SL {stop_loss_price} | Target {target_price}")
                else:
                    print("❌ Live entry failed. Waiting for next signal.")
                    pos_type = ""
                    entry_price = 0.0
                    entry_time = None
                    entry_data = {}
                    stop_loss_price = None
                    target_price = None

            price_history.append({
                "DateTime": current_time,
                "Price": current_price,
                "High": float(df['High'].iloc[-1]),
                "Low": float(df['Low'].iloc[-1]),
                "Volume": float(df['Volume'].iloc[-1]) if 'Volume' in df.columns else 0,
                "Signal": action,
                "RSI": signal_data.get('rsi'),
                "RSI_FAST": signal_data.get('rsi_fast'),
                "EMA_FAST": signal_data.get('ema_f'),
                "SLOPE": signal_data.get('slope'),
                "PERCENT_B": signal_data.get('percent_b') if 'percent_b' in signal_data else None,
                "REGIME": signal_data.get('regime'),
                "Stop_Loss": stop_loss_price,
                "Target": target_price
            })
            time.sleep(300)
        except Exception as e:
            print(f"❌ Live trading error: {e}")
            time.sleep(60)


def save_trade_and_price_files(trades, price_history, trade_path, price_path):
    report_df = pd.DataFrame(trades)
    report_df.to_csv(trade_path, index=False)
    price_history_df = pd.DataFrame(price_history)
    price_history_df.to_csv(price_path, index=False)
    return report_df, price_history_df


def run_paper_trading():
    """Simulate paper trading with no real-money orders."""
    print("🧪 Starting PAPER TRADING MODE (no real money)")
    print(f"📡 Fetching today's {CONFIG['SYMBOL']} 5-minute candles...")

    df = yf.download(CONFIG['SYMBOL'], period="7d", interval="5m")
    if df.empty:
        print("❌ Data is empty")
        return

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()
    df = df[df.index.date == datetime.now().date()]
    if df.empty:
        print("❌ No intraday data available for today yet.")
        return

    df = df.between_time("09:15", "15:15")
    if df.empty or len(df) < 30:
        print("❌ Insufficient market-hours candles for paper trading.")
        return

    data_records = df.reset_index().to_dict('records')
    trades = []
    price_history = []
    in_position = False
    pos_type, entry_price, entry_time = "", 0.0, None
    entry_data = {}
    stop_loss_price = None
    target_price = None

    print(f"📊 Simulating {len(data_records)} intraday candles...")

    for i in range(30, len(data_records)):
        params = risk_management()
        row = data_records[i]
        now_time, now_close = row['Datetime'], float(row['Close'])

        price_window = [r['Close'] for r in data_records[i-25:i+1]]
        if len(price_window) < 20:
            continue

        signal_data = calculate_signals(
            price_list=price_window,
            current_time=now_time,
            position=(1 if pos_type == "LONG" else -1) if in_position else 0,
            entry_price=entry_price
        )

        if in_position:
            pnl_pct = ((now_close - entry_price) / entry_price) if pos_type == "LONG" else ((entry_price - now_close) / entry_price)
            if pnl_pct >= params['breakeven_pct']:
                if pos_type == "LONG":
                    stop_loss_price = max(stop_loss_price or entry_price, entry_price)
                    stop_loss_price = max(stop_loss_price, entry_price * (1 + params['trail_distance']))
                else:
                    stop_loss_price = min(stop_loss_price or entry_price, entry_price)
                    stop_loss_price = min(stop_loss_price, entry_price * (1 - params['trail_distance']))

        price_history.append({
            "DateTime": now_time,
            "Price": now_close,
            "High": float(row['High']),
            "Low": float(row['Low']),
            "Volume": float(row['Volume']) if 'Volume' in row else 0,
            "Signal": signal_data.get('action', 'WAIT'),
            "RSI": signal_data.get('rsi'),
            "RSI_FAST": signal_data.get('rsi_fast'),
            "EMA_FAST": signal_data.get('ema_f'),
            "SLOPE": signal_data.get('slope'),
            "PERCENT_B": signal_data.get('percent_b') if 'percent_b' in signal_data else None,
            "REGIME": signal_data.get('regime'),
            "Stop_Loss": stop_loss_price,
            "Target": target_price
        })

        action = signal_data.get('action', 'WAIT')
        exit_reason = None

        if in_position:
            if stop_loss_price is not None and ((pos_type == "LONG" and now_close <= stop_loss_price) or (pos_type == "SHORT" and now_close >= stop_loss_price)):
                exit_reason = "EXIT_SL"
            elif target_price is not None and ((pos_type == "LONG" and now_close >= target_price) or (pos_type == "SHORT" and now_close <= target_price)):
                exit_reason = "EXIT_TARGET"
            elif action.startswith("EXIT"):
                exit_reason = action

        if not in_position and action in ["BUY_LONG", "SELL_SHORT"]:
            pos_type = "LONG" if action == "BUY_LONG" else "SHORT"
            entry_price = now_close * (1 + (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
            entry_time = now_time
            entry_data = signal_data
            stop_loss_price = entry_price * (1 - params['stop_loss_pct']) if pos_type == "LONG" else entry_price * (1 + params['stop_loss_pct'])
            target_price = entry_price * (1 + params['target_pct_3']) if pos_type == "LONG" else entry_price * (1 - params['target_pct_3'])
            in_position = True
            print(f"🟢 Paper entry simulated: {pos_type} at {entry_price:.2f} | SL {stop_loss_price:.2f} | Target {target_price:.2f}")
            continue

        if in_position and exit_reason is not None:
            exit_price = now_close * (1 - (CONFIG['SLIPPAGE_BPS'] if pos_type == "LONG" else -CONFIG['SLIPPAGE_BPS']))
            points = (exit_price - entry_price) if pos_type == "LONG" else (entry_price - exit_price)
            net_pnl = (points * CONFIG['LOT_SIZE']) - params['brokerage_fee']
            trades.append({
                "Trade_ID": f"PAPER_{len(trades)+1}",
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
                "Exit_RSI": signal_data.get('rsi')
            })
            print(f"🔴 Paper exit simulated: {pos_type} closed at {exit_price:.2f} @ {now_time} | PnL: ₹{net_pnl:.2f} ({exit_reason})")
            in_position = False
            pos_type = ""
            entry_price = 0.0
            entry_time = None
            entry_data = {}
            stop_loss_price = None
            target_price = None

    if trades:
        report_df, price_history_df = save_trade_and_price_files(trades, price_history, CONFIG['PAPER_OUTPUT_FILE'], CONFIG['PRICE_HISTORY_FILE'])
        print(f"\n✅ PAPER TRADING COMPLETE. Trades: {len(report_df)} | Total PnL: ₹{report_df['Net_PnL'].sum():,.2f}")
        print(f"   Price history written to {CONFIG['PRICE_HISTORY_FILE']}")
        print(f"   Paper trades written to {CONFIG['PAPER_OUTPUT_FILE']}")
    else:
        pd.DataFrame(price_history).to_csv(CONFIG['PRICE_HISTORY_FILE'], index=False)
        print("\n⚠️ No paper trades were generated today.")
        print(f"   Price history still saved to {CONFIG['PRICE_HISTORY_FILE']}")


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
        print("⚠️  Live trading with multiple strategies coming soon!")
        print("   For now, running paper trading with best strategy...")
        run_paper_trading()
    elif CONFIG['PAPER_MODE']:
        run_paper_trading()
    else:
        run_angel_backtest()
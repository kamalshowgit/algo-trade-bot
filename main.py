"""
FILE: main.py
AUTHOR: Kamal Soni (Quant Research)
VERSION: 8.0 "Production Ready - Nifty F&O"

CHANGES:
  - Added EXIT_ALL dispatcher for EOD Square-off (3:15 PM)
  - Fixed duplicate logging methods (Resolved KeyError)
  - Synchronized LOT_SIZE to 65 (Nifty April 2026 contract)
"""

import time
import pyotp
import csv
import os
from collections import deque
from datetime import datetime

import engine
from SmartApi import SmartConnect
from config import API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET


# ===========================================================================
# CONFIG  —  NIFTY FUTURES SETTINGS
# ===========================================================================
CAPITAL          = 100000        # Capital ₹1 Lakh
LOT_SIZE         = 65            # Nifty April 2026 Lot Size
BROKERAGE        = 60            # ₹ per round-trip
ACTIVE_STRATEGY  = "moderate"    
SYMBOL           = "NIFTY30APR26FUT"
TOKEN            = "35000"       # April Future Token ID
EXCHANGE_SEG     = "NFO"         # Derivatives Exchange
HISTORY_SIZE     = 200           
TICK_SLEEP       = 1             
MAX_ERRORS       = 5             
MARKET_CLOSE_H   = 15
MARKET_CLOSE_M   = 25
TRADE_LOG_FILE   = "paper_trade_history.csv"
SIGNAL_LOG_FILE  = "paper_signal_history.csv"
# ===========================================================================


def create_session():
    api = SmartConnect(api_key=API_KEY)
    api.generateSession(CLIENT_ID, PASSWORD, pyotp.TOTP(TOTP_SECRET).now())
    return api


class PaperTrader:
    def __init__(self, initial_capital):
        self.capital     = initial_capital
        self.position    = 0        # +65 for Long, -65 for Short
        self.entry_price = 0.0
        self.total_pnl   = 0.0

        if not os.path.exists(TRADE_LOG_FILE):
            with open(TRADE_LOG_FILE, 'w', newline='') as f:
                csv.writer(f).writerow([
                    "Timestamp", "Strategy", "Side", "Price", "Qty",
                    "Trade_PnL", "Total_PnL", "RSI_Value",
                ])

        if not os.path.exists(SIGNAL_LOG_FILE):
            with open(SIGNAL_LOG_FILE, 'w', newline='') as f:
                csv.writer(f).writerow([
                    "Timestamp", "Strategy", "Signal", "LTP",
                    "RSI_Value", "MA_20", "BB_Upper", "BB_Lower", "Position",
                ])

    def _write_log(self, ts, strat, side, price, qty, pnl, data):
        """Standardized logging to match performance audit script."""
        rsi_val = data.get('rsi') if data.get('rsi') is not None else data.get('RSI_Value', 0)
        
        with open(TRADE_LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([
                ts, strat, side, price, qty, 
                round(pnl, 2), round(self.total_pnl, 2), rsi_val
            ])

    def execute_paper_trade(self, side, strategy_used, engine_data):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        price     = engine_data['price']
        trade_pnl = 0.0

        # --- ENTRY LOGIC ---
        if side == "BUY_LONG" and self.position == 0:
            self.entry_price = price
            self.position    = LOT_SIZE
            self._write_log(timestamp, strategy_used, "BUY", price, LOT_SIZE, 0, engine_data)
            print(f"📝 [LONG ENTRY]  ₹{price} | RSI: {engine_data.get('rsi')}")

        elif side == "SELL_SHORT" and self.position == 0:
            self.entry_price = price
            self.position    = -LOT_SIZE
            self._write_log(timestamp, strategy_used, "SELL", price, LOT_SIZE, 0, engine_data)
            print(f"🔻 [SHORT ENTRY] ₹{price} | RSI: {engine_data.get('rsi')}")

        # --- EXIT LOGIC ---
        elif side == "EXIT_LONG" and self.position > 0:
            trade_pnl = (price - self.entry_price) * LOT_SIZE
            self._finalize_trade(trade_pnl, price, "SELL", strategy_used, engine_data)

        elif side == "EXIT_SHORT" and self.position < 0:
            trade_pnl = (self.entry_price - price) * LOT_SIZE 
            self._finalize_trade(trade_pnl, price, "BUY", strategy_used, engine_data)

    def _finalize_trade(self, trade_pnl, price, side, strategy, engine_data):
        net_pnl = trade_pnl - BROKERAGE
        self.total_pnl += net_pnl
        self.capital   += net_pnl
        print(f"💰 [EXIT] Net: ₹{net_pnl:.2f} | Total P&L: ₹{self.total_pnl:.2f}")
        
        self._write_log(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
            strategy, side, price, LOT_SIZE, trade_pnl, engine_data
        )
        self.position = 0
        self.entry_price = 0

    def log_signal(self, strategy_used, engine_data, ltp):
        with open(SIGNAL_LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                strategy_used, engine_data.get('action', 'WAIT'),
                ltp, engine_data.get('rsi', 0), engine_data.get('ma', 0),
                engine_data.get('upper', 0), engine_data.get('lower', 0), self.position,
            ])


def run_bot():
    now_dt       = datetime.now()
    market_close = now_dt.replace(hour=MARKET_CLOSE_H, minute=MARKET_CLOSE_M, second=0)

    if now_dt > market_close:
        print(f"🕒 Market closed. Exiting.")
        return

    try:
        api = create_session()
        print(f"✅ SESSION ACTIVE | {SYMBOL} ({EXCHANGE_SEG})")
    except Exception as e:
        print(f"❌ Login Failed: {e}")
        return

    bot        = PaperTrader(initial_capital=CAPITAL)
    history    = deque(maxlen=HISTORY_SIZE)
    api_errors = 0

    print(f"📊 Tracking {SYMBOL} | Strategy: {ACTIVE_STRATEGY.upper()}")

    while True:
        try:
            current_time = datetime.now()
            if current_time > market_close:
                print(f"🏁 Session ended at {current_time.strftime('%H:%M:%S')}")
                break

            res = api.ltpData(EXCHANGE_SEG, SYMBOL, TOKEN)

            if res.get('status') is True:
                api_errors = 0
                ltp        = res['data']['ltp']
                history.append(ltp)

                engine_data = engine.calculate_signals(
                    price_list    = list(history),
                    current_pnl   = bot.total_pnl,
                    capital       = bot.capital,
                    current_time  = current_time,
                    strategy_name = ACTIVE_STRATEGY,
                )

                signal = engine_data.get("action", "WAIT")
                bot.log_signal(ACTIVE_STRATEGY, engine_data, ltp)

                if signal == "STOP_FOR_DAY":
                    print(f"🚨 Daily Loss Limit Reached.")
                    break

                # --- SIGNAL DISPATCHER ---
                if signal == "BUY_LONG" and bot.position == 0:
                    bot.execute_paper_trade("BUY_LONG", ACTIVE_STRATEGY, engine_data)
                elif signal == "SELL_SHORT" and bot.position == 0:
                    bot.execute_paper_trade("SELL_SHORT", ACTIVE_STRATEGY, engine_data)
                elif signal == "EXIT_LONG" and bot.position > 0:
                    bot.execute_paper_trade("EXIT_LONG", ACTIVE_STRATEGY, engine_data)
                elif signal == "EXIT_SHORT" and bot.position < 0:
                    bot.execute_paper_trade("EXIT_SHORT", ACTIVE_STRATEGY, engine_data)
                
                # Handle Force EOD Exit from Engine
                elif signal == "EXIT_ALL" and bot.position != 0:
                    exit_side = "EXIT_LONG" if bot.position > 0 else "EXIT_SHORT"
                    bot.execute_paper_trade(exit_side, ACTIVE_STRATEGY, engine_data)

            time.sleep(TICK_SLEEP)

        except Exception as e:
            api_errors += 1
            if api_errors >= MAX_ERRORS:
                print("🔄 Reconnecting...")
                try:
                    api = create_session()
                    api_errors = 0
                except: pass
            time.sleep(2)


if __name__ == "__main__":
    run_bot()
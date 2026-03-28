"""
FILE: main.py
AUTHOR: Kamal Soni (Quant Research)
SYMBOL: NIFTYBEES-EQ (NSE ETF tracking Nifty 50)

COMPATIBILITY GUARANTEED:
  review_performance.py reads CSV columns:
    Timestamp, Strategy, Side, Price, Qty, Trade_PnL, Total_PnL, RSI_Value  ✅
  engine.py calculate_signals returns:
    action, price, rsi, ma, upper, lower                                     ✅
  config.py supplies:
    API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET                                ✅

IMPROVEMENTS OVER ORIGINAL:
  [M1]  collections.deque(maxlen=200) replaces list + manual pop(0)
        — O(1) append, no off-by-one, correct buffer for EMA-50
  [M2]  market_close as full datetime (not .time()) — no midnight wraparound
  [M3]  All magic numbers in one CONFIG block at the top
  [M4]  Dynamic qty: 2% of remaining capital / price (not hardcoded)
  [M5]  Slippage already applied by engine — no double-counting
  [M6]  capital updated after every exit to reflect real remaining capital
  [M7]  Auto-reconnect: re-authenticates after MAX_ERRORS consecutive failures
  [M8]  CSV column 'RSI_Value' kept to match review_performance.py exactly
  [M9]  Signal log (every tick) added for post-session analysis
  [M10] Brokerage constant matches engine.risk_management() value (₹100)
  [M11] qty logged correctly for both BUY and SELL rows
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
# CONFIG  —  edit ONLY this block
# ===========================================================================
CAPITAL          = 1000000        # Starting capital ₹
RISK_PER_TRADE   = 0.02          # 2% of capital per trade for position sizing [M4]
BROKERAGE        = 100           # ₹ per round-trip, matches engine.risk_management [M10]
ACTIVE_STRATEGY  = "moderate"    # "sniper" | "scalper" | "moderate"
SYMBOL = "Nifty 50"
TOKEN = "99926000"
HISTORY_SIZE     = 200           # deque maxlen — covers EMA-50 warm-up      [M1]
TICK_SLEEP       = 1             # seconds between API polls
MAX_ERRORS       = 5             # consecutive errors before reconnect attempt [M7]
MARKET_CLOSE_H   = 15
MARKET_CLOSE_M   = 35
TRADE_LOG_FILE   = "paper_trade_history.csv"
SIGNAL_LOG_FILE  = "paper_signal_history.csv"
# ===========================================================================


# ---------------------------------------------------------------------------
# SESSION
# ---------------------------------------------------------------------------
def create_session():
    """Authenticates and returns a live SmartConnect session."""
    api = SmartConnect(api_key=API_KEY)
    api.generateSession(
        CLIENT_ID,
        PASSWORD,
        pyotp.TOTP(TOTP_SECRET).now()   # fresh TOTP on every call
    )
    return api


# ---------------------------------------------------------------------------
# PAPER TRADER
# ---------------------------------------------------------------------------
class PaperTrader:
    def __init__(self, initial_capital):
        self.capital     = initial_capital
        self.position    = 0        # units held
        self.entry_price = 0.0
        self.entry_qty   = 0
        self.total_pnl   = 0.0

        # ── Trade log ─────────────────────────────────────────────────────
        # Columns kept identical to what review_performance.py expects  [M8]
        if not os.path.exists(TRADE_LOG_FILE):
            with open(TRADE_LOG_FILE, 'w', newline='') as f:
                csv.writer(f).writerow([
                    "Timestamp", "Strategy", "Side", "Price", "Qty",
                    "Trade_PnL", "Total_PnL", "RSI_Value",
                ])

        # ── Signal log (every tick) ───────────────────────────────────────
        if not os.path.exists(SIGNAL_LOG_FILE):
            with open(SIGNAL_LOG_FILE, 'w', newline='') as f:
                csv.writer(f).writerow([
                    "Timestamp", "Strategy", "Signal", "LTP",
                    "RSI_Value", "MA_20", "BB_Upper", "BB_Lower", "Position",
                ])

    # ── Dynamic qty ───────────────────────────────────────────────────────
    def _calc_qty(self, price):
        """2% of remaining capital / price, minimum 1 unit."""           # [M4]
        if price <= 0:
            return 1
        return max(int((self.capital * RISK_PER_TRADE) / price), 1)

    # ── Execute paper trade ───────────────────────────────────────────────
    def execute_paper_trade(self, side, strategy_used, engine_data):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        price     = engine_data['price']   # slippage already applied by engine [M5]
        trade_pnl = 0.0

        if side == "BUY" and self.position == 0:
            qty              = self._calc_qty(price)
            self.entry_price = price
            self.entry_qty   = qty
            self.position    = qty
            print(f"📝 [{strategy_used} BUY]  ₹{price} × {qty} "
                  f"| RSI: {engine_data.get('rsi', 0)}")

        elif side == "SELL" and self.position > 0:
            qty       = self.entry_qty                     # sell what we bought
            trade_pnl = (price - self.entry_price) * qty
            net_pnl   = trade_pnl - BROKERAGE
            self.total_pnl += net_pnl
            self.capital   += net_pnl                      # track real capital [M6]
            self.position   = 0
            self.entry_qty  = 0
            print(f"💰 [{strategy_used} SELL] ₹{price} × {qty} "
                  f"| Net: ₹{net_pnl:.2f} | Total P&L: ₹{self.total_pnl:.2f}")
        else:
            return   # invalid state — skip log

        # Log row — RSI_Value column matches review_performance.py     [M8, M11]
        with open(TRADE_LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([
                timestamp, strategy_used, side,
                price, qty,
                round(trade_pnl, 2),
                round(self.total_pnl, 2),
                engine_data.get('rsi', 0),        # column: RSI_Value [M8]
            ])

    # ── Log every tick ────────────────────────────────────────────────────
    def log_signal(self, strategy_used, engine_data, ltp):            # [M9]
        with open(SIGNAL_LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                strategy_used,
                engine_data.get('action', 'WAIT'),
                ltp,
                engine_data.get('rsi',   0),
                engine_data.get('ma',    0),
                engine_data.get('upper', 0),
                engine_data.get('lower', 0),
                self.position,
            ])


# ---------------------------------------------------------------------------
# MAIN BOT LOOP
# ---------------------------------------------------------------------------
def run_bot():
    # Market close as full datetime — no midnight wraparound          [M2]
    now_dt       = datetime.now()
    market_close = now_dt.replace(
        hour=MARKET_CLOSE_H, minute=MARKET_CLOSE_M,
        second=0, microsecond=0
    )

    if now_dt > market_close:
        print(f"🕒 Market already closed (past {MARKET_CLOSE_H}:{MARKET_CLOSE_M:02d}). Exiting.")
        return

    # Login
    try:
        api = create_session()
        print(f"✅ Session Active")
        print(f"   Capital    : ₹{CAPITAL:,.0f}")
        print(f"   Strategy   : {ACTIVE_STRATEGY.upper()}")
        print(f"   Symbol     : {SYMBOL}")
        print(f"   Risk/trade : {RISK_PER_TRADE*100:.0f}%  |  Brokerage: ₹{BROKERAGE}")
        print(f"   Loss limit : ₹{CAPITAL * 0.01:,.0f}  |  Closes: {MARKET_CLOSE_H}:{MARKET_CLOSE_M:02d}\n")
    except Exception as e:
        print(f"❌ Login Failed: {e}")
        return

    bot        = PaperTrader(initial_capital=CAPITAL)
    history    = deque(maxlen=HISTORY_SIZE)                           # [M1]
    api_errors = 0

    print(f"📊 Paper Trading running | Tick: {TICK_SLEEP}s | Buffer: {HISTORY_SIZE} ticks")

    while True:
        try:
            current_time = datetime.now()

            if current_time > market_close:
                print(f"\n🏁 {MARKET_CLOSE_H}:{MARKET_CLOSE_M:02d} reached. Session closed.")
                print(f"   Final P&L : ₹{bot.total_pnl:,.2f}")
                print(f"   Remaining : ₹{bot.capital:,.2f}")
                break

            # ── Fetch LTP ─────────────────────────────────────────────────
            res = api.ltpData("NSE", SYMBOL, TOKEN)

            if res.get('status') is True:
                api_errors = 0
                ltp        = res['data']['ltp']
                history.append(ltp)

                # ── Engine call ───────────────────────────────────────────
                engine_data = engine.calculate_signals(
                    price_list    = history,
                    current_pnl   = bot.total_pnl,
                    capital       = bot.capital,   # live remaining capital [M6]
                    current_time  = current_time,
                    strategy_name = ACTIVE_STRATEGY,
                )

                signal = engine_data.get("action", "WAIT")

                # ── Log every tick ────────────────────────────────────────
                bot.log_signal(ACTIVE_STRATEGY, engine_data, ltp)    # [M9]

                # ── Circuit breaker ───────────────────────────────────────
                if signal == "STOP_FOR_DAY":
                    print(f"\n🚨 CIRCUIT BREAKER: 1% daily loss hit.")
                    print(f"   Final P&L: ₹{bot.total_pnl:,.2f}")
                    break

                # ── Trade execution ───────────────────────────────────────
                if signal == "BUY" and bot.position == 0:
                    bot.execute_paper_trade("BUY",  ACTIVE_STRATEGY, engine_data)
                elif signal == "SELL" and bot.position > 0:
                    bot.execute_paper_trade("SELL", ACTIVE_STRATEGY, engine_data)

            else:
                print(f"⚠️  Unexpected API response: {res}")

            time.sleep(TICK_SLEEP)

        except Exception as e:
            api_errors += 1
            print(f"⚠️  Error #{api_errors}: {e}")

            # ── Auto-reconnect ────────────────────────────────────────────
            if api_errors >= MAX_ERRORS:                               # [M7]
                print("🔄 Attempting session reconnect...")
                try:
                    api        = create_session()
                    api_errors = 0
                    print("✅ Reconnected.")
                except Exception as re_err:
                    print(f"❌ Reconnect failed: {re_err}. Stopping bot.")
                    break
            else:
                time.sleep(5)


if __name__ == "__main__":
    run_bot()
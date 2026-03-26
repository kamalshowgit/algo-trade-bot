import time, pyotp, config, engine, csv, os
from SmartApi import SmartConnect
from datetime import datetime

class PaperTrader:
    def __init__(self, initial_capital=5000):
        self.capital = initial_capital
        self.position = 0  
        self.entry_price = 0
        self.total_pnl = 0
        self.trade_log_file = "paper_trade_history.csv"
        
        # Added columns for Technical Indicators (RSI, MA, etc.) to the header
        if not os.path.exists(self.trade_log_file):
            with open(self.trade_log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "Strategy", "Side", "Price", "Qty", 
                    "Trade_PnL", "Total_PnL", "RSI_Value", "BB_Mean", "BB_Upper", "BB_Lower"
                ])

    def execute_paper_trade(self, side, qty, strategy_used, tech_data):
        trade_pnl = 0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        brokerage_per_cycle = 60  # ₹50 brokerage + taxes
        price = tech_data['price']

        if side == "BUY" and self.position <= 0:
            self.entry_price = price
            self.position = qty
            print(f"📝 [{strategy_used} BUY] Price: {price} | RSI: {tech_data['rsi']}")
            
        elif side == "SELL" and self.position > 0:
            trade_pnl = (price - self.entry_price) * qty
            net_pnl = trade_pnl - brokerage_per_cycle
            self.total_pnl += net_pnl
            
            print(f"💰 [{strategy_used} EXIT] Price: {price} | Net: ₹{net_pnl:.2f} | RSI: {tech_data['rsi']}")
            self.position = 0

        # Log including Strategy name AND Technical Metadata
        with open(self.trade_log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp, strategy_used, side, price, qty, 
                trade_pnl, self.total_pnl, 
                tech_data['rsi'], tech_data['ma'], tech_data['upper'], tech_data['lower']
            ])

def run_bot():
    now = datetime.now().time()
    market_close = datetime.strptime("15:35:00", "%H:%M:%S").time()
    
    if now > market_close:
        print("🕒 15:35 reached. Market is closed.")
        return

    try:
        api = SmartConnect(api_key=config.API_KEY)
        api.generateSession(config.CLIENT_ID, config.PASSWORD, pyotp.TOTP(config.TOTP_SECRET).now())
        print("✅ Paper Session Active (Using Angel One Live Feed)")
    except Exception as e:
        print(f"❌ Login Failed: {e}")
        return

    paper_bot = PaperTrader(initial_capital=5000)
    history = []
    symbol = "NIFTYBEES-EQ" 
    token = "10531" 
    qty = 19 

    # --- TOGGLE STRATEGY HERE ---
    ACTIVE_STRATEGY = "sniper" 

    print(f"📊 Paper HFT Active | Strategy: {ACTIVE_STRATEGY.upper()} | Symbol: {symbol}")

    while True:
        try:
            if datetime.now().time() > market_close:
                break

            res = api.ltpData("NSE", symbol, token)
            
            if res['status'] == True:
                ltp = res['data']['ltp']
                history.append(ltp)
                if len(history) > 100: history.pop(0) 
                
                # Receive full dictionary from the engine
                engine_data = engine.calculate_signals(history, strategy_name=ACTIVE_STRATEGY) 
                signal = engine_data["action"]
                
                if signal == "BUY" and paper_bot.position == 0:
                    paper_bot.execute_paper_trade("BUY", qty, ACTIVE_STRATEGY, engine_data)
                elif signal == "SELL" and paper_bot.position > 0:
                    paper_bot.execute_paper_trade("SELL", qty, ACTIVE_STRATEGY, engine_data)
            
            time.sleep(1) 

        except Exception as e:
            print(f"⚠️ Runtime Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_bot()

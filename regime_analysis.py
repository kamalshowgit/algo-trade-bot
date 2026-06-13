import pandas as pd
import yfinance as yf
import sys
import os
import numpy as np

def fetch_daily_data(symbol="^NSEI", period="2y"):
    """Fetches daily data to calculate long-term market regimes."""
    print("Fetching daily market data for regime classification...")
    df = yf.download(symbol, period=period, interval="1d", progress=False)
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    df = df.reset_index()
    if "Date" in df.columns:
        df.rename(columns={"Date": "Datetime"}, inplace=True)
        
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    
    if df["Datetime"].dt.tz is not None:
        df["Datetime"] = df["Datetime"].dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
        
    return df

def classify_regimes(df):
    """
    Classify each day into Bull, Bear, or Sideways.
    Using a 50-day SMA and ATR for volatility/sideways detection.
    """
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    
    # Calculate ATR (Average True Range) for 14 days
    df['TR'] = np.maximum((df['High'] - df['Low']), 
                          np.maximum(abs(df['High'] - df['Close'].shift(1)), 
                                     abs(df['Low'] - df['Close'].shift(1))))
    df['ATR_14'] = df['TR'].rolling(window=14).mean()
    
    # Define Regime
    # Bull: Close > SMA_50 and distance > 0.5 * ATR
    # Bear: Close < SMA_50 and distance > 0.5 * ATR
    # Sideways: Distance to SMA_50 < 0.5 * ATR
    
    def get_regime(row):
        if pd.isna(row['SMA_50']) or pd.isna(row['ATR_14']):
            return "UNKNOWN"
            
        distance = row['Close'] - row['SMA_50']
        threshold = 0.5 * row['ATR_14']
        
        if abs(distance) <= threshold:
            return "SIDEWAYS"
        elif distance > threshold:
            return "BULL"
        else:
            return "BEAR"
            
    df['Regime'] = df.apply(get_regime, axis=1)
    
    # Keep only date for joining
    df['Date_Only'] = df['Datetime'].dt.date
    return df[['Date_Only', 'Regime']]

def run_regime_analysis(csv_file):
    if not os.path.exists(csv_file):
        print(f"❌ Cannot find '{csv_file}'.")
        return

    print(f"Loading trades from {csv_file}...")
    trades_df = pd.read_csv(csv_file)
    trades_df['Entry_Time'] = pd.to_datetime(trades_df['Entry_Time'])
    trades_df['Date_Only'] = trades_df['Entry_Time'].dt.date
    
    market_df = fetch_daily_data()
    
    regime_df = classify_regimes(market_df)
    
    # Merge trades with regimes
    merged_df = pd.merge(trades_df, regime_df, on='Date_Only', how='left')
    
    # Analyze performance per regime
    regimes = ["BULL", "BEAR", "SIDEWAYS", "UNKNOWN"]
    
    print("\n" + "="*80)
    print("                 MARKET REGIME ANALYSIS")
    print("="*80)
    
    for regime in regimes:
        subset = merged_df[merged_df['Regime'] == regime]
        num_trades = len(subset)
        if num_trades == 0:
            continue
            
        total_pnl = subset['Net_PnL'].sum()
        win_rate = (len(subset[subset['Net_PnL'] > 0]) / num_trades) * 100
        avg_trade = total_pnl / num_trades
        
        gross_profit = subset[subset['Net_PnL'] > 0]['Net_PnL'].sum()
        gross_loss = abs(subset[subset['Net_PnL'] <= 0]['Net_PnL'].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)
        
        print(f"\n--- {regime} MARKET ---")
        print(f"Trades:        {num_trades}")
        print(f"Total PnL:     {round(total_pnl, 2)}")
        print(f"Win Rate:      {round(win_rate, 2)}%")
        print(f"Avg Trade:     {round(avg_trade, 2)}")
        print(f"Profit Factor: {round(profit_factor, 2)}")

    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    strategy = sys.argv[1] if len(sys.argv) > 1 else "strategy_1"
    target_file = f"{strategy}_backtest_results.csv"
    run_regime_analysis(target_file)

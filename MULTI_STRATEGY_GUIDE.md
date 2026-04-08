# Multi-Strategy Trading Bot Setup

## Overview
Your trading bot now supports **4 different trading strategies** that are tested simultaneously during backtesting and paper trading. Each strategy has its own logic and performance metrics are compared to identify the best performer.

## The 4 Strategies

### 1. **Strategy 1 - EMA Alignment** (Original)
- **Logic**: EMA stack alignment with RSI and Bollinger Bands confirmation
- **Best For**: Trending markets with clear directional bias
- **Entry Signals**:
  - Long: EMA very_fast > fast > slow + RSI > 42 + Percent_B < 0.65
  - Short: EMA very_fast < fast < slow + RSI < 58 + Percent_B > 0.35
- **Exit Signals**: Scaling targets, momentum reversal, stop loss

### 2. **Strategy 2 - RSI Mean Reversion**
- **Logic**: RSI overbought/oversold with recovery/weakness confirmation
- **Best For**: Range-bound, mean reverting markets
- **Entry Signals**:
  - Long: RSI < 35 + RSI rising + Price above slow EMA
  - Short: RSI > 65 + RSI falling + Price below slow EMA
- **Exit Signals**: RSI normalization, profit targets, stop loss

### 3. **Strategy 3 - Bollinger Bands**
- **Logic**: Price action at Bollinger Band extremes with momentum confirmation
- **Best For**: Volatile markets with clear support/resistance
- **Entry Signals**:
  - Long: Price near lower band + upward slope + RSI recovering
  - Short: Price near upper band + downward slope + RSI weakening
- **Exit Signals**: Mean reversion to middle band, scaling targets, stop loss

### 4. **Strategy 4 - Breakout & Momentum**
- **Logic**: Strong momentum and price breakout with trend confirmation
- **Best For**: Breakout traders, trending markets with strong moves
- **Entry Signals**:
  - Long: Slope > 0.0015 + Velocity > 0.0005 + ROC > 0.08 + Price > EMA_fast > EMA_slow
  - Short: Slope < -0.0015 + Velocity < -0.0005 + ROC < -0.08 + Price < EMA_fast < EMA_slow
- **Exit Signals**: Momentum reversal, scaling targets, stop loss

## How to Run

### Backtest (All 4 Strategies)
```bash
# Default mode - runs multi-strategy backtest
python3 main.py

# Output files:
# - strategy_1_backtest_results.csv
# - strategy_2_backtest_results.csv
# - strategy_3_backtest_results.csv
# - strategy_4_backtest_results.csv
# - price_history.csv
```

### Paper Trading (All 4 Strategies)
```bash
# Set PAPER_MODE=true in .env
PAPER_MODE=true python3 main.py
```

### Live Trading (Single Best Strategy)
```bash
# Live trading will use the best performing strategy (coming soon)
LIVE_MODE=true python3 main.py
```

## Configuration

### Environment Variables (.env)
```
# Email Configuration
SENDER_EMAIL=your-email@gmail.com
APP_PASSWORD=your-app-password
RECEIVER_EMAIL=recipient1@email.com,recipient2@email.com

# Trading Modes
LIVE_MODE=false
PAPER_MODE=true

# Output Files
TRADE_DATA_PATH=./paper_trade_history.csv
PRICE_HISTORY_PATH=./price_history.csv
BACKTEST_RESULTS_PATH=./angel_backtest_results.csv

# Angel One Credentials
ANGEL_API_KEY=your_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_password
ANGEL_TOTP_SECRET=your_totp_secret
```

## Email Reporting

### What You'll Receive
The email report now includes:

1. **Best Strategy Identification**: Shows which strategy performed best (🏆)
2. **Strategy Comparison Table**: Side-by-side comparison of all 4 strategies:
   - Total PnL
   - Number of Trades
   - Win Rate %
3. **Best Strategy Metrics**:
   - Total P&L and Average P&L per trade
   - Profit Factor, Expectancy
   - Win Rate, Max Drawdown
   - Trade duration analysis
4. **Price History**: Market data summary for the day
5. **Top 5 Trades**: Best performing trades from best strategy
6. **Attachments**:
   - `trades_summary.csv` - All trades (best strategy)
   - `price_history_minute_by_minute.csv` - Minute-by-minute price data

### Email Recipients
- All recipients are in **BCC** so they don't see each other's emails
- Add multiple recipients separated by commas

## File Structure

```
algo-trade-bot/
├── main.py                           # Main trading engine
├── engine.py                         # 4 trading strategies
├── send_email_report.py             # Multi-strategy email reports
├── requirements.txt                 # Dependencies
├── .env                             # Configuration
├── ecosystem.config.js              # PM2 configuration
├── housekeeping.sh                  # Cleanup script
├── push_results.sh                  # Results push script
├── README.md                        # Project overview
├── MULTI_STRATEGY_GUIDE.md         # This file
│
├── Outputs:
├── strategy_1_backtest_results.csv
├── strategy_2_backtest_results.csv
├── strategy_3_backtest_results.csv
├── strategy_4_backtest_results.csv
├── price_history.csv
└── logs/ 
    └── [dated folders with trade logs]
```

## Forward Testing Strategy

Forward testing allows you to validate strategies on live market data without real money:

1. **Paper Trading Mode**: Simulates trades on historic data with slippage and fees
2. **Email Reports**: Get detailed metrics for each strategy
3. **Compare Performance**: Identify which strategy works best for current market conditions
4. **Select Best**: Use the best-performing strategy for live trading

## Performance Metrics Explained

| Metric | Definition |
|--------|-----------|
| **Total PnL** | Sum of all trade profits/losses |
| **Win Rate** | % of trades that were profitable |
| **Profit Factor** | Total Profit / Total Loss (higher is better) |
| **Expectancy** | Average profit per trade |
| **Max Drawdown** | Largest peak-to-trough decline |
| **Avg Duration** | Average time held in each trade |

## Tips for Best Results

1. **Run Daily Backtests**: Test strategies on fresh data daily
2. **Compare Output Files**: Each strategy has its own CSV file for detailed analysis
3. **Monitor Email Reports**: Shows which strategy worked best for yesterday's market conditions
4. **Adjust Risk Parameters**: Edit `risk_management()` in engine.py to tune SL/target percentages
5. **Watch for Regime Changes**: If a strategy's performance drops, the market regime may have changed

## Risk Management

All strategies use these common risk parameters:
- **Stop Loss**: 0.10% per trade
- **Breakeven**: Move SL to breakeven at +0.02% profit
- **Trailing**: Trail stops by 0.03% once profitable
- **Targets**: Scale out at +0.04%, +0.06%, +0.08%
- **Brokerage Fee**: ₹60 per round-trip

## Troubleshooting

### No trades generated
- Check market hours (9:15 AM - 3:15 PM IST weekdays)
- Verify data is being fetched correctly
- Check if price action meets strategy entry conditions

### Email not received
- Verify SENDER_EMAIL and APP_PASSWORD in .env
- Check RECEIVER_EMAIL format (comma-separated)
- Check Gmail security settings for app-specific passwords

### Inconsistent results
- Some variation is normal due to market volatility
- Each strategy responds differently to market conditions
- Track performance over multiple days for better insights

## Next Steps

1. ✅ Run initial backtest to understand strategy performance
2. ✅ Review email reports to see strategy comparison
3. ✅ Analyze individual strategy CSV files for deeper insights
4. ✅ Paper trade for 2-3 days to validate in real market conditions
5. ✅ Enable live trading with best-performing strategy when confident

Good luck with your trading! 🚀

# Algo Trade Bot

Intraday trading bot for NIFTY-style instruments with:

- Angel One market data for forward paper trading
- 4 intraday strategies
- Multi-strategy backtesting
- PM2-based server scheduling
- Email reporting

This repo is now documented in one place so deployment is easier.

## Current Behavior

- `PAPER_MODE=true` uses Angel One data and simulates trades without placing real-money orders.
- `LIVE_MODE=true` is still routed to paper mode by default for safety.
- Backtesting still uses `yfinance`.
- Forward paper trading uses a single configurable strategy.

## Strategies

The engine includes 4 intraday strategies in `engine.py`:

1. `strategy_1`: EMA alignment
2. `strategy_2`: RSI mean reversion
3. `strategy_3`: Bollinger mean reversion
4. `strategy_4`: Breakout momentum

All strategies are intraday-only and operate during market hours. They use shared stop loss, target, break-even, and trailing rules from `risk_management()`.

## Important Notes

- These strategies are designed for intraday trading, not guaranteed daily profit.
- Brokerage, slippage, and instrument selection have a large impact on results.
- For realistic forward testing, keep your Angel market-data symbol/token aligned with the instrument you care about.

## Project Files

Core runtime files:

- `main.py`: entrypoint, paper mode, backtest mode, Angel integration
- `engine.py`: indicators, risk rules, strategies
- `send_email_report.py`: end-of-day email summary
- `requirements.txt`: Python dependencies
- `ecosystem.config.js`: PM2 schedule and process config
- `deploy_and_start.sh`: automated deployment helper
- `health_check.sh`: quick health check
- `status_check.sh`: quick PM2 status
- `troubleshoot.sh`: deeper diagnostics
- `housekeeping.sh`: basic cleanup helper
- `push_results.sh`: optional result-push helper

Generated runtime outputs are intentionally not kept in the repo.

## Environment Variables

Use `.env.example` as the template.

Required Angel credentials:

- `ANGEL_API_KEY`
- `ANGEL_CLIENT_ID`
- `ANGEL_PASSWORD`
- `ANGEL_TOTP_SECRET`

Required email config:

- `SENDER_EMAIL`
- `RECEIVER_EMAIL`
- `GMAIL_APP_PASSWORD`

Trading mode:

- `LIVE_MODE=false`
- `PAPER_MODE=true`

Angel forward paper data:

- `MARKET_DATA_EXCHANGE=NSE`
- `MARKET_DATA_SYMBOL=NIFTY`
- `MARKET_DATA_SYMBOL_TOKEN=99926000`
- `MARKET_DATA_INTERVAL=FIVE_MINUTE`
- `MARKET_POLL_SECONDS=30`
- `CANDLE_LOOKBACK_DAYS=2`
- `FORWARD_STRATEGY=strategy_1`

Optional live-order instrument settings:

- `TRADE_EXCHANGE=NSE`
- `TRADE_SYMBOL=NIFTY30APR26FUT`
- `TRADE_SYMBOL_TOKEN=99926000`

Output file path:

- `TRADE_DATA_PATH=./paper_trade_history.csv`

## Local Run

Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run forward paper trading:

```bash
python3 main.py
```

Run backtest mode:

```bash
PAPER_MODE=false LIVE_MODE=false python3 main.py
```

Select a different forward strategy:

```bash
FORWARD_STRATEGY=strategy_4 python3 main.py
```

## Ubuntu or EC2 Deployment

Install base packages:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nodejs npm
sudo npm install -g pm2
```

Copy the project to the server, then:

```bash
chmod +x deploy_and_start.sh health_check.sh status_check.sh troubleshoot.sh housekeeping.sh push_results.sh
bash deploy_and_start.sh
```

Manual setup if needed:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pm2 start ecosystem.config.js
pm2 save
pm2 status
```

## PM2 Behavior

The PM2 config in `ecosystem.config.js` is set up for weekday scheduling:

- start at `09:15` IST
- stop at `15:20` IST

Useful commands:

```bash
pm2 status
pm2 logs HFT_Bot --lines 50
pm2 restart HFT_Bot
pm2 stop HFT_Bot
pm2 delete HFT_Bot
```

Helper scripts:

```bash
./status_check.sh
./health_check.sh
./troubleshoot.sh
```

## How Forward Paper Trading Works

Paper mode in `main.py`:

- logs into Angel One
- fetches recent candles from Angel
- polls for fresh market data during intraday hours
- calculates signals for the configured strategy
- simulates entries and exits only
- force-closes any open paper position at market close
- writes trade and price-history CSV output

The active strategy is controlled by `FORWARD_STRATEGY`.

## How Backtesting Works

Backtesting mode:

- downloads historical 5-minute data using `yfinance`
- runs all 4 strategies
- compares total PnL, trade count, and win rate
- writes per-strategy output CSVs

Backtesting is useful for relative comparison, but forward paper results are more important before any live rollout.

## Troubleshooting

If the bot exits immediately:

- confirm dependencies installed in the active virtualenv
- confirm `.env` exists and Angel credentials are valid
- run `./troubleshoot.sh`

If no paper trades appear:

- verify market hours
- verify `MARKET_DATA_SYMBOL` and `MARKET_DATA_SYMBOL_TOKEN`
- try another `FORWARD_STRATEGY`
- check logs with `pm2 logs HFT_Bot --lines 100`

If email fails:

- verify `SENDER_EMAIL`, `RECEIVER_EMAIL`, and `GMAIL_APP_PASSWORD`
- confirm Gmail app password is being used

## Deployment Checklist

- `.env` created on server
- Angel credentials added
- email credentials added
- virtualenv created
- `pip install -r requirements.txt` completed
- PM2 installed
- `pm2 start ecosystem.config.js` working
- `pm2 save` completed
- health check passes

## Recommended Next Step

Deploy with:

```bash
bash deploy_and_start.sh
```

Then verify:

```bash
./health_check.sh
pm2 status
pm2 logs HFT_Bot --lines 50
```

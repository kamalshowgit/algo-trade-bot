# Quick Start Guide

## 📋 What's in the Repository

### Production Core Files ✅
```
engine.py                 → Trading logic & signal generation
main.py                   → Backtesting & live trading orchestrator
send_email_report.py      → Daily performance email
```

### Configuration & Support
```
requirements.txt          → Python dependencies
.env                      → Credentials (NOT committed to git)
.env.example              → Template for .env setup
ecosystem.config.js       → PM2 process configuration
```

### Testing & Utilities
```
test_connection.py        → Test Angel One broker connection
system_check.py           → Validate all components
housekeeping.sh          → Log rotation script
```

### Documentation 📖
```
SYSTEM_OVERVIEW.md        → Complete system architecture & strategy
AWS_DEPLOYMENT.md         → Step-by-step AWS setup guide
```

### Output & Logs
```
logs/                     → Trading execution logs
angel_backtest_results.csv → Trade history after runs
price_history.csv         → Minute-by-minute pricing data
```

---

## 🚀 Getting Started Locally

### 1. Setup Environment
```bash
# Clone repository
git clone <your-repo-url>
cd algo-trade-bot

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Credentials
```bash
# Copy environment template
cp .env.example .env

# Edit with your credentials
nano .env
# Add Angel One API keys and email settings
```

### 3. Test Connection
```bash
# Verify everything works
python system_check.py
python test_connection.py
```

### 4. Run Backtest
```bash
# Test with historical data
python main.py
```

---

## 🎯 Current Performance

**Backtest Results (v4 - Current):**
- **Trades Generated:** 20
- **Win Rate:** 35% (7 wins, 13 losses)
- **Total P&L:** -₹11,745.21
- **Avg Per Trade:** -₹587.26
- **Optimization:** 90% improvement from v1 (−₹115k → −₹11.7k)

**Key Achievement:** Strategy went from losing ₹1,032 per trade to only ₹587 per trade through trend-aware filtering.

---

## ☁️ AWS Deployment (3 Steps)

### Option A: Lambda (Simplest)
```bash
# See AWS_DEPLOYMENT.md → Option 1: Lambda
# Upload zip file → Set environment variables → Schedule EventBridge
```

### Option B: EC2 (More Control)
```bash
# See AWS_DEPLOYMENT.md → Option 2: EC2
# Launch instance → Clone repo → Install deps → Setup cron
```

### Option C: CodePipeline (Most Automated)
```bash
# Use GitHub Actions + CodePipeline for auto-deployment
# Triggers on git push to main branch
```

---

## 🔄 How Trading Works

### Entry Logic
1. **Analyze Market** - Check EMA alignment (Uptrend/Downtrend/Choppy)
2. **Generate Signal** - Look for:
   - EMA crossovers (3 > 5 > 12 or opposite)
   - Momentum confirmation (slope > 0.0008)
   - RSI validation (42-58 range, not extreme)
3. **Enter Position** - Buy/Sell with 0.10% stop-loss

### Exit Logic
1. **Micro Profit** +0.04% → Take it (EXIT_SCALE_1)
2. **Small Profit** +0.06% → Close (EXIT_SCALE_2)
3. **Medium Profit** +0.08% → Exit (EXIT_SCALE_3)
4. **Reversal** - Momentum turns → Exit immediately
5. **Hard Stop** -0.10% → Cut loss (EXIT_SL)

---

## 📊 Trading Strategy Breakdown

| Component | Details |
|-----------|---------|
| **Timeframe** | 5-minute candles |
| **Instrument** | NIFTY 50 Index (^NSEI) |
| **Hours** | 9:15 AM - 3:15 PM IST |
| **Indicators** | EMA(3,5,12), RSI(7,14), Bollinger Bands, Slope, Velocity |
| **Per-Trade Target** | +0.04% to +0.08% profit |
| **Per-Trade Risk** | -0.10% stop-loss |
| **Strategy** | Trend-aware EMA scalping |
| **Signal Type** | EMA alignment + momentum confirmation |

---

## ⚙️ Configuration Tuning

### Aggressive Settings (More Trades, Less Selective)
```python
# In engine.py risk_management():
"stop_loss_pct": 0.0012,        # Wider stop (0.12% vs 0.10%)
"target_pct_1": 0.0003,         # Smaller target (0.03% vs 0.04%)
```

### Conservative Settings (Fewer Trades, Higher Quality)
```python
# In engine.py risk_management():
"stop_loss_pct": 0.0008,        # Tighter stop (0.08% vs 0.10%)
"target_pct_1": 0.0005,         # Larger target (0.05% vs 0.04%)
```

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Import errors | Run `pip install -r requirements.txt` |
| Connection fails | Check `.env` credentials, run `test_connection.py` |
| No trades generated | Check market hours (9:15-3:15 IST), verify data fetching |
| P&L negative | This is expected in development - see backtest results |
| Email not sending | Verify `EMAIL_PASSWORD` is App Password (not regular PWD) |

---

## 📈 Next Steps to Profitability

| Phase | Action | Status |
|-------|--------|--------|
| **Phase 1** | Fix core trading logic | ✅ Complete |
| **Phase 2** | Implement trend filtering | ✅ Complete |
| **Phase 3** | Optimize entry selectivity | ✅ Complete |
| **Phase 4** | Test lower profit targets | ⏳ Next |
| **Phase 5** | Extended backtest (6+ months) | ⏳ Next |
| **Phase 6** | Enable live trading | ⏳ After validation |

---

## 📞 Key Files to Modify

### To Adjust Trading Parameters
- **File:** `engine.py`
- **Function:** `risk_management()` - Adjust stop-loss, profit targets
- **Function:** `strategy_logic()` - Modify entry thresholds (RSI levels, slope, etc.)

### To Change Broker
- **File:** `main.py`
- **Function:** `place_order()` - Replace Angel One with your broker API

### To Schedule Differently
- **File:** `ecosystem.config.js` (PM2 config)
- **Or:** Crontab entry on EC2/Lambda EventBridge rule

---

## ✅ Pre-Deployment Checklist

- [ ] `.env` file created with credentials
- [ ] `python system_check.py` passes all tests
- [ ] `python test_connection.py` connects to Angel One
- [ ] `python main.py` generates trades without errors
- [ ] CSV outputs created successfully
- [ ] Email sending test works
- [ ] `.env` is in `.gitignore` (never committed)
- [ ] All secret files removed (venv, __pycache__, etc.)
- [ ] README.md updated with setup instructions
- [ ] Ready to push to GitHub/CodeCommit

---

## 🎓 Learning Resources

**Understanding the Strategy:**
1. Read `SYSTEM_OVERVIEW.md` - Complete technical breakdown
2. Study `engine.py` → `strategy_logic()` - Main trading logic
3. Check backtest results in `angel_backtest_results.csv`

**AWS Deployment:**
1. Follow `AWS_DEPLOYMENT.md` - Step-by-step guide
2. Choose Lambda vs EC2 based on your needs
3. Set up monitoring in CloudWatch

**Optimization:**
1. Backtest with different parameters
2. Analyze trade CSV for patterns
3. Adjust entry thresholds and profit targets

---

Generated: April 5, 2026
Last Updated: v4 (Trend-Aware EMA Scalping)

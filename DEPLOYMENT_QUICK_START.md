# 📋 Ubuntu/EC2 Deployment - Quick Reference

## 🎯 What This Does

You now have a complete production-ready trading bot with:
- ✅ 4 simultaneous trading strategies
- ✅ Automatic PM2 scheduling (9:15 AM - 3:15 PM IST)
- ✅ Multi-strategy comparison emails
- ✅ Comprehensive troubleshooting tools
- ✅ Health checks and monitoring

## 🚀 First-Time Deployment (Copy & Paste)

### SSH to Your Server
```bash
ssh ubuntu@your-ec2-ip
cd ~/trading_bot
```

### Run Deployment (One Command)
```bash
bash deploy_and_start.sh
```

This automatically:
1. Creates/activates Python virtual env
2. Installs all dependencies
3. Validates Python syntax
4. Checks/installs PM2
5. Deploys with PM2
6. Saves PM2 config for persistence

### Verify It's Running
```bash
bash status_check.sh
```

## 📊 Helper Scripts (Ready to Use)

| Script | Purpose |
|--------|---------|
| `deploy_and_start.sh` | 🚀 Complete deployment (run first) |
| `health_check.sh` | 🏥 Pre-market health check |
| `status_check.sh` | 📊 Quick status overview |
| `troubleshoot.sh` | 🔧 Full diagnostics |

### Usage Examples

```bash
# Before market open (run daily)
bash health_check.sh

# Check current status
bash status_check.sh

# Full diagnostics if something's wrong
bash troubleshoot.sh

# View live logs
pm2 logs HFT_Bot

# Restart if needed
pm2 restart HFT_Bot
```

## 🕐 Automatic Schedule (PST Configuration)

Your bot automatically:
- **9:15 AM IST** → Starts (Monday-Friday)
- **3:15-3:20 PM IST** → Stops gracefully
- **Repeat** → Next market day

This is handled by PM2 cron jobs in `ecosystem.config.js`.

## ✅ Daily Workflow

### Morning (Before 9:15 AM IST)
```bash
bash health_check.sh          # Verify everything is ready
pm2 logs HFT_Bot --lines 5    # Check for any issues
```

### Afternoon (After 3:15 PM IST)
```bash
ls -la strategy_*.csv         # Check if strategies ran
pm2 describe HFT_Bot          # Verify it shut down
```

### Email Report
Check your inbox for the multi-strategy comparison report with:
- All 4 strategy performance side-by-side
- Best performing strategy highlighted (🏆)
- Top 5 profitable trades
- Market data summary
- CSV attachments for analysis

## 🔍 Understanding PM2 Status

### "stopped" or "…90m" Status = ✅ NORMAL

This is expected behavior:
- Bot runs 9:15 AM - 3:15 PM IST
- Exits gracefully at market close (exit code 0)
- PM2 doesn't restart outside market hours
- Automatically restarts at 9:15 AM via `cron_restart`

### "online" Status = ✅ RUNNING (During Market Hours)

If you see "online" between 9:15 AM - 3:15 PM IST, the bot is trading.

## 🛠️ Common Commands

```bash
# Check status
pm2 status
pm2 describe HFT_Bot

# View logs
pm2 logs HFT_Bot          # Live tail
pm2 logs HFT_Bot --err    # Errors only
pm2 logs HFT_Bot -l 100   # Last 100 lines

# Control process
pm2 restart HFT_Bot       # Restart
pm2 stop HFT_Bot          # Stop gracefully
pm2 start HFT_Bot         # Start manually
pm2 delete HFT_Bot        # Remove (only if needed)

# Check logs directory
tail -f logs/out.log      # Direct file access
tail -f logs/err.log      # Error logs
```

## 📁 File Structure

```
~/trading_bot/
├── main.py                    # Main bot engine
├── engine.py                  # 4 trading strategies
├── send_email_report.py       # Email reports
├── ecosystem.config.js        # PM2 config
├── .env                       # Configuration
├── venv/                      # Python virtual env
├── logs/                      # PM2 logs
├── strategy_*.csv             # Results (generated daily)
├── price_history.csv          # Market data
│
├── Helper Scripts:
├── deploy_and_start.sh        # Full deployment
├── health_check.sh            # Pre-market check
├── status_check.sh            # Quick status
└── troubleshoot.sh            # Diagnostics
```

## 🔧 Setup Issues & Fixes

### Bot exits immediately with "No intraday data"
✅ **This is NORMAL** - means market data isn't available yet
- Happens before 9:15 AM or after 3:15 PM IST
- Bot exits gracefully and waits for market open
- PM2 will restart at 9:15 AM IST

### "No space left on device"
```bash
# Check disk space
df -h

# Clean old logs (keep 5 days)
find logs/ -mtime +5 -delete
```

### Email not working
```bash
# 1. Verify config
grep "EMAIL\|RECEIVER" .env

# 2. Test manually
python3 -c "from send_email_report import send_email; send_email()"

# 3. Check logs
pm2 logs HFT_Bot | grep -i email
```

### Process won't start at 9:15 AM
```bash
# Check cron config
pm2 describe HFT_Bot | grep cron

# Test manual start
pm2 start ecosystem.config.js

# View PM2 logs for cron events
pm2 logs PM2 | grep cron
```

## 🔐 Security Checklist

- [ ] Keep `.env` permissions: `chmod 600 .env`
- [ ] Rotate Gmail app passwords monthly
- [ ] Use SSH key for GitHub access
- [ ] Don't commit `.env` to git
- [ ] Monitor logs for errors

## 📈 Performance Monitoring

### Check Daily Results
```bash
# Total trades from all strategies
cat strategy_*.csv | wc -l

# Today's total P&L
python3 << 'EOF'
import pandas as pd, glob
total = sum(pd.read_csv(f)['Net_PnL'].sum() for f in glob.glob("strategy_*.csv"))
print(f"Total P&L: ₹{total:,.2f}")
EOF
```

### Monitor Resource Usage
```bash
# Real-time monitoring
watch 'pm2 status'

# Check memory usage
ps aux | grep main.py

# View system resources
free -h
df -h
```

## 🆘 Emergency Help

```bash
# Complete reset (if stuck)
pm2 kill
sleep 2
bash deploy_and_start.sh

# View detailed error
bash troubleshoot.sh

# Check all logs
pm2 logs HFT_Bot --err --lines 200
```

## 📞 Quick Diagnostics Checklist

Before reporting an issue, run:

```bash
# 1. Health check
bash health_check.sh

# 2. Full diagnostics
bash troubleshoot.sh

# 3. Get error details
pm2 logs HFT_Bot --err --lines 100 > error_report.txt
cat error_report.txt
```

## 🎓 Learning Resources

- PM2 Docs: `pm2 help`
- Cron Schedule Info: `pm2 describe HFT_Bot | grep cron`
- Python Packages: `pip list`
- System Info: `uname -a`

## ✨ Next Steps

1. ✅ Copy all files to Ubuntu server (`git clone` or scp)
2. ✅ Run `bash deploy_and_start.sh`
3. ✅ Run `bash health_check.sh` before market open
4. ✅ Check email inbox after market close
5. ✅ Review `MULTI_STRATEGY_GUIDE.md` for strategy details

## 🚀 You're Ready!

Your bot is now production-ready with automatic scheduling, multi-strategy trading, and comprehensive monitoring.

**Good luck with your trading! 📈**

---

## 📚 Related Documentation

- `MULTI_STRATEGY_GUIDE.md` - Trading strategy details
- `UBUNTU_DEPLOYMENT.md` - Comprehensive deployment guide
- `SETUP_COMPLETE.md` - What's been configured
- `README.md` - Project overview

---

*Last updated: April 9, 2026*
*For support: Check logs with `pm2 logs HFT_Bot`*

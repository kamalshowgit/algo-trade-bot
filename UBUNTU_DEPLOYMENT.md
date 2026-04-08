# 🚀 Ubuntu/EC2 Deployment Guide

## Quick Start - Copy & Paste Commands

```bash
cd ~/trading_bot

# 1. Make scripts executable
chmod +x deploy_and_start.sh troubleshoot.sh status_check.sh

# 2. Run deployment
bash deploy_and_start.sh

# 3. Check status
bash status_check.sh

# 4. View logs
pm2 logs HFT_Bot
```

---

## 📋 What's Happening Now

### Current Setup on Your Ubuntu Server:

Your bot is configured as follows:

```
⏰ Scheduled Start:  9:15 AM IST (Market Open) - Weekdays Only (Mon-Fri)
⏰ Scheduled Stop:   3:20 PM IST (After Market Close)
💾 Data Storage:    ./strategy_*_backtest_results.csv
📊 Logs Location:   ./logs/
📧 Email Reports:   Sent automatically after trading
```

### Why PM2 Shows "stopped" or "…90m":

This is **NORMAL behavior**! Here's why:

1. **Non-market hours**: The bot exits gracefully (code 0) when there's no data
2. **PM2 doesn't restart**: Because `stop_exit_codes: [0]` prevents auto-restart on graceful exit
3. **Cron waits**: PM2 will automatically restart at 9:15 AM IST with `cron_restart`
4. **Graceful stop**: PM2 stops the process at 3:20 PM IST with `cron_stop`

This is actually **optimal behavior** - no wasted resources outside market hours!

---

## 🔧 Deployment Steps

### Step 1: SSH to Your Server
```bash
ssh ubuntu@your-ec2-ip
cd ~/trading_bot
```

### Step 2: Make Scripts Executable
```bash
chmod +x *.sh
ls -la *.sh  # Verify they're executable
```

### Step 3: Run Full Deployment
```bash
bash deploy_and_start.sh
```

This script will:
- ✅ Check/create Python virtual environment
- ✅ Install missing dependencies
- ✅ Validate all Python files
- ✅ Verify PM2 is installed
- ✅ Create logs directory
- ✅ Deploy process with PM2
- ✅ Save PM2 config for persistence

### Step 4: Verify Deployment
```bash
# Quick status
bash status_check.sh

# Full diagnostic
bash troubleshoot.sh

# View live logs
pm2 logs HFT_Bot
```

---

## 📊 Understanding the Output

### "No intraday data available for today yet"
This message means:
- ✅ Bot is running correctly
- ⏰ Market data isn't available yet (before 9:15 AM or after market close)
- 😊 Bot will exit gracefully and wait for next market open

### Normal Daily Flow:

```
9:15 AM IST  → PM2 starts bot (cron_restart)
9:15-15:15   → Bot runs, generates trades, sends email
3:15 PM IST  → Bot exits gracefully (market close)
3:20 PM IST  → PM2 stops bot (cron_stop)
3:20 PM-9:15 AM → Bot stays stopped
9:15 AM IST  → PM2 starts bot again (cron_restart)
```

---

## 🛠️ Common Operations

### Check Current Status
```bash
pm2 status                    # Quick overview
pm2 describe HFT_Bot          # Detailed info
pm2 logs HFT_Bot              # Live logs
pm2 logs HFT_Bot --lines 50   # Last 50 lines
```

### Restart Bot
```bash
pm2 restart HFT_Bot           # Restart process
pm2 stop HFT_Bot              # Stop gracefully
pm2 start HFT_Bot             # Start process
pm2 delete HFT_Bot            # Remove from PM2
```

### View Logs
```bash
pm2 logs HFT_Bot              # Live output
pm2 logs HFT_Bot --err        # Error logs only
tail -f logs/err.log          # Direct file access
tail -f logs/out.log          # Output logs
```

### Update Code & Restart
```bash
cd ~/trading_bot
git pull origin main          # Get latest code
pm2 restart HFT_Bot           # Restart with new code
pm2 logs HFT_Bot              # Check if it's running
```

---

## 📧 Email Verification

### Step 1: Verify `.env` Configuration
```bash
cd ~/trading_bot
cat .env | grep -E "^(SENDER_EMAIL|APP_PASSWORD|RECEIVER_EMAIL)"

# Should show:
# SENDER_EMAIL=your-email@gmail.com
# APP_PASSWORD=your-16-char-app-password
# RECEIVER_EMAIL=recipient@email.com,another@email.com
```

### Step 2: Test Email Manually
```bash
cd ~/trading_bot
source venv/bin/activate

python3 << 'EOF'
from send_email_report import send_email
print("Testing email...")
send_email()
print("Done!")
EOF
```

### Step 3: Check Email Logs
```bash
pm2 logs HFT_Bot | grep -i email
```

---

## 🐛 Troubleshooting

### Bot Exits Immediately
```bash
# Check for errors
bash troubleshoot.sh

# View detailed logs
pm2 logs HFT_Bot --err --lines 50

# Test Python manually
python3 main.py
```

### No Email Reports Received
```bash
# Check email config
grep "EMAIL\|RECEIVER" .env

# Test email manually
python3 << 'EOF'
from send_email_report import send_email
send_email()
EOF

# Check Gmail app passwords
# See: https://myaccount.google.com/apppasswords
```

### Process Not Starting at 9:15 AM
```bash
# Verify cron config
pm2 describe HFT_Bot | grep cron

# Check PM2 log for cron events
pm2 logs PM2 | grep cron

# Manual start for testing
pm2 start HFT_Bot
```

### High Memory Usage
```bash
# Check current memory
free -h

# Monitor real-time
watch 'pm2 status'

# Check process details
ps aux | grep main.py
```

---

## 🔒 Security Best Practices

### Protect Your `.env` File
```bash
chmod 600 .env
ls -la .env  # Should show: -rw------- (only owner can read/write)
```

### Rotate Credentials Regularly
```bash
# Update APP_PASSWORD
# See: https://myaccount.google.com/apppasswords
nano .env  # Update APP_PASSWORD value
pm2 restart HFT_Bot
```

### Use SSH Keys for Git
```bash
# Generate key if not exists
ssh-keygen -t ed25519 -C "your-email@example.com"

# Add to GitHub: https://github.com/settings/keys
cat ~/.ssh/id_ed25519.pub
```

---

## 📈 Performance Monitoring

### Daily Checklist
```bash
# Morning (9:20 AM IST)
pm2 status                # Check if bot started
pm2 logs HFT_Bot          # Check for errors

# Afternoon (3:00 PM IST)
ls -la strategy_*.csv     # Check if results generated
pm2 describe HFT_Bot      # Check uptime

# End of Day (after 3:20 PM)
# Check email in inbox
# Verify trades executed
```

### Track Key Metrics
```bash
# Total trades (all strategies)
cat strategy_*_backtest_results.csv | wc -l

# Best strategy results
sort -t',' -k8 -nr strategy_*_backtest_results.csv | head -3

# Today's PnL
python3 << 'EOF'
import pandas as pd
import glob

total_pnl = 0
for file in glob.glob("strategy_*.csv"):
    df = pd.read_csv(file)
    total_pnl += df['Net_PnL'].sum()
    print(f"{file}: ₹{df['Net_PnL'].sum():,.2f}")
print(f"Total PnL (all strategies): ₹{total_pnl:,.2f}")
EOF
```

---

## 🚨 Emergency Commands

```bash
# Stop everything
pm2 kill

# Restart after kill
pm2 start ecosystem.config.js
pm2 save

# Restore after reboot
pm2 resurrect

# Complete reset
pm2 delete all
pm2 start ecosystem.config.js
```

---

## 📱 Useful Shortcuts

### Create Aliases (Optional)
Add to `~/.bashrc` then `source ~/.bashrc`:

```bash
alias bot-status='pm2 status'
alias bot-logs='pm2 logs HFT_Bot'
alias bot-restart='pm2 restart HFT_Bot'
alias bot-stop='pm2 stop HFT_Bot'
alias bot-check='bash ~/trading_bot/troubleshoot.sh'
```

Then use:
```bash
bot-status    # Instead of pm2 status
bot-logs      # Instead of pm2 logs HFT_Bot
bot-restart   # Instead of pm2 restart HFT_Bot
```

---

## 📞 Need Help?

### Check Logs First
```bash
pm2 logs HFT_Bot --lines 100
```

### Run Diagnostics
```bash
bash troubleshoot.sh
```

### Review Configuration
```bash
pm2 describe HFT_Bot
cat ecosystem.config.js
```

### Git Sync Issues
```bash
cd ~/trading_bot
git status
git log --oneline -5
```

---

## 🎯 Next Steps

1. **Deploy**: `bash deploy_and_start.sh`
2. **Verify**: `bash status_check.sh`
3. **Monitor**: `pm2 logs HFT_Bot`
4. **Tomorrow**: Check if email was received

Your bot is ready! 🚀📈

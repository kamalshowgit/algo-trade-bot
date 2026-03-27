#!/bin/bash
# 1. Navigate to the folder
cd /home/ubuntu/trading_bot

# 2. Get today's date for the branch name
DATE=$(date +%Y-%m-%d)

# 3. Create a new branch for today
git checkout -b trade-logs-$DATE

# 4. Add the data files (CSV and Logs)
git add paper_trade_history.csv logs/out.log

# 5. Commit and Push
git commit -m "Auto-pushing trade results for $DATE"
git push origin trade-logs-$DATE

# 6. Switch back to main for Monday
git checkout main

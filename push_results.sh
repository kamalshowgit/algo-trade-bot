#!/bin/bash
# 1. Navigate to the folder
cd /home/ubuntu/trading_bot

# 2. Get today's date for the branch name
DATE=$(date +%Y-%m-%d)

# 3. Create or checkout the branch for today
git checkout -B trade-logs-$DATE

# 4. Add the data files (CSV and Logs)
git add *.csv logs/*.log

# 5. Commit and Push
if git diff --staged --quiet; then
    echo "No changes to commit for $DATE"
else
    git commit -m "Auto-pushing trade results for $DATE"
    git push -u origin trade-logs-$DATE
fi

# 6. Switch back to main for Monday
git checkout main

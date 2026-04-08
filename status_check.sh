#!/bin/bash

# Quick status check script
# Shows current bot status and next action

TZ='Asia/Kolkata' date
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
pm2 status
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if process is running
if pm2 list | grep -q "HFT_Bot"; then
    STATUS=$(pm2 describe HFT_Bot | grep "status" | head -1)
    echo "Process Status: $STATUS"
    echo ""
    echo "Recent Activity:"
    pm2 logs HFT_Bot --lines 5 --nostream
else
    echo "❌ Process not found in PM2"
fi

echo ""
echo "Next Steps:"
echo "  - View full logs: pm2 logs HFT_Bot"
echo "  - Restart bot: pm2 restart HFT_Bot"
echo "  - Stop bot: pm2 stop HFT_Bot"
echo "  - View config: pm2 describe HFT_Bot"

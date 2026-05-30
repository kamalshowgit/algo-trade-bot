#!/bin/bash
cd /home/ubuntu/trading_bot

TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

# Move old logs to a compressed archive to save space
echo -e "\n=== ARCHIVED ON $TIMESTAMP ===" >> logs/historical_archive.log
cat logs/out.log >> logs/historical_archive.log
echo -e "\n=== ARCHIVED ON $TIMESTAMP ===" >> logs/historical_err_archive.log
cat logs/err.log >> logs/historical_err_archive.log

# Wipe the active files to zero bytes
> logs/out.log
> logs/err.log

# Delete any temporary Python cache or temp files
find . -name "*.pyc" -delete
find . -name "__pycache__" -delete
rm -f *.tmp

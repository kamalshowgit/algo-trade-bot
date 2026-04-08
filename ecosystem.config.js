module.exports = {
  apps : [{
    name: "HFT_Bot",
    script: "./main.py",
    interpreter: "./venv/bin/python3",
    
    // ===== SCHEDULING & RESTART =====
    // Starts the bot at 9:15 AM IST (market open), Monday to Friday
    cron_restart: "15 9 * * 1-5",
    
    // Graceful restart at 3:20 PM IST (after market close)
    cron_stop: "20 15 * * 1-5",
    
    // Prevents infinite restart loops with exponential backoff
    autorestart: true,
    exp_backoff_restart_delay: 100,
    max_restarts: 5,
    min_uptime: "10s",
    
    // Exit codes: 0 = normal exit (don't restart), other = crash (restart)
    stop_exit_codes: [0],
    
    // ===== PROCESS MANAGEMENT =====
    instances: 1,
    exec_mode: "fork",
    max_memory_restart: "500M",
    watch: false,
    
    // ===== LOGGING & TIMEOUTS =====
    timeout: 30000,
    listen_timeout: 3000,
    kill_timeout: 5000,
    wait_ready: true,
    
    // ===== ENVIRONMENT =====
    env: {
      NODE_ENV: "production",
      TZ: "Asia/Kolkata"
    },
    
    // ===== ERROR HANDLING =====
    error_file: "./logs/err.log",
    out_file: "./logs/out.log",
    log_file: "./logs/combined.log",
    combine_logs: true
  }]
}
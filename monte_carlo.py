import pandas as pd
import numpy as np
import sys
import os

def run_monte_carlo(csv_file, iterations=10000, initial_capital=100000, risk_of_ruin_threshold=50000):
    """
    Runs a Monte Carlo simulation by reshuffling the sequence of trades.
    """
    if not os.path.exists(csv_file):
        print(f"❌ Cannot find '{csv_file}'. Please run backtest.py first.")
        return

    print(f"Loading trade data from {csv_file}...")
    try:
        trades_df = pd.read_csv(csv_file)
        if 'Net_PnL' not in trades_df.columns:
            print("❌ 'Net_PnL' column missing from CSV.")
            return
            
        trades = trades_df['Net_PnL'].tolist()
    except Exception as e:
        print(f"❌ Failed to parse trades: {e}")
        return
        
    num_trades = len(trades)
    if num_trades == 0:
        print("❌ No trades to simulate.")
        return

    print(f"Running Monte Carlo Simulation ({iterations} iterations)...")
    
    final_capitals = []
    max_drawdowns = []
    ruin_count = 0
    
    for _ in range(iterations):
        # Randomly reshuffle the trade sequence
        shuffled_trades = np.random.choice(trades, size=num_trades, replace=True)
        
        # Calculate equity curve for this iteration
        equity_curve = initial_capital + np.cumsum(shuffled_trades)
        
        # Final capital
        final_cap = equity_curve[-1]
        final_capitals.append(final_cap)
        
        # Risk of ruin (Did it ever dip below the threshold?)
        if np.any(equity_curve < risk_of_ruin_threshold):
            ruin_count += 1
            
        # Max Drawdown for this iteration
        # Running maximum
        running_max = np.maximum.accumulate(equity_curve)
        # Avoid division by zero if running_max somehow hits 0
        running_max[running_max == 0] = 1 
        drawdowns = (running_max - equity_curve) / running_max
        max_drawdowns.append(np.max(drawdowns))

    # Calculate statistics
    final_capitals = np.array(final_capitals)
    max_drawdowns = np.array(max_drawdowns)
    
    expected_return = np.mean(final_capitals) - initial_capital
    prob_of_ruin = (ruin_count / iterations) * 100
    
    print("\n" + "="*60)
    print(f"                 MONTE CARLO SIMULATION RESULTS")
    print("="*60)
    print(f"Initial Capital:         {initial_capital}")
    print(f"Iterations:              {iterations}")
    print(f"Trades per iteration:    {num_trades}")
    print("-" * 60)
    print(f"Expected Final Capital:  {round(np.mean(final_capitals), 2)}")
    print(f"Median Final Capital:    {round(np.median(final_capitals), 2)}")
    print(f"Worst Case (Min):        {round(np.min(final_capitals), 2)}")
    print(f"Best Case (Max):         {round(np.max(final_capitals), 2)}")
    print("-" * 60)
    print(f"5th Percentile Outcome:  {round(np.percentile(final_capitals, 5), 2)}  <- (95% chance to beat this)")
    print(f"95th Percentile Outcome: {round(np.percentile(final_capitals, 95), 2)}  <- (Only 5% chance to beat this)")
    print("-" * 60)
    print(f"Expected Max Drawdown:   {round(np.mean(max_drawdowns) * 100, 2)}%")
    print(f"95th Percentile MDD:     {round(np.percentile(max_drawdowns, 95) * 100, 2)}%  <- (Worst expected drawdown)")
    print(f"Probability of Ruin:     {round(prob_of_ruin, 2)}%   <- (Chance of capital dropping below {risk_of_ruin_threshold})")
    print("="*60 + "\n")


if __name__ == "__main__":
    strategy = sys.argv[1] if len(sys.argv) > 1 else "strategy_1"
    target_file = f"{strategy}_backtest_results.csv"
    run_monte_carlo(target_file)

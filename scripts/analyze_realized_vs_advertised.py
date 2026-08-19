"""Main result: time-weighted average advertised APY vs. realized return from liquidityIndex.

The chart is the argument: the daily-sampled series (one snapshot per UTC day, naively
averaged) is plotted against the full-resolution series (every raw event, held for its true
duration) on the same axes. The daily series spikes well above a full-resolution line that
sits close to the realized return almost everywhere, because the full-resolution series shows
brief spikes as brief (thin), not stretched across whole days.
"""
import os

import matplotlib.pyplot as plt
import pandas as pd

DAILY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "usdc_daily_rates.csv")
RAW_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "usdc_raw_events.csv")
CHART_PATH = os.path.join(os.path.dirname(__file__), "..", "charts", "apy_vs_realized.png")

RAY = 10**27
SECONDS_PER_YEAR = 31536000

# From the full raw fetch (891,932 rows, first/last by timestamp) — see prior run output.
# The daily-resampled CSV's first row is the *last* update of day 1, not the window's true
# first observation, so it understates the realized return slightly (3.6626% vs 3.6663%);
# this is the precise figure tied to the actual window boundaries.
REALIZED_RETURN_PCT = (1.1820654587021906 / 1.140260048268024 - 1) * 100


def liquidity_rate_to_apy_pct(raw_liquidity_rate):
    apr = int(raw_liquidity_rate) / RAY
    apy = (1 + apr / SECONDS_PER_YEAR) ** SECONDS_PER_YEAR - 1
    return apy * 100


def time_weighted_average_apy(df):
    dates = pd.to_datetime(df["date"])
    weights = (dates.shift(-1) - dates).dt.days
    weights = weights.iloc[:-1]
    rates = df["liquidityRate"].iloc[:-1]
    return (rates * weights).sum() / weights.sum()


def main():
    daily = pd.read_csv(DAILY_PATH)
    raw = pd.read_csv(RAW_PATH).sort_values("timestamp").reset_index(drop=True)
    raw["apy"] = raw["liquidityRate"].apply(liquidity_rate_to_apy_pct)
    raw["datetime"] = pd.to_datetime(raw["timestamp"], unit="s", utc=True)

    tw_avg_apy = time_weighted_average_apy(daily)
    gap_pp = tw_avg_apy - REALIZED_RETURN_PCT

    print(f"time-weighted average advertised APY (daily-sampled): {tw_avg_apy:.4f}%")
    print(f"realized return (liquidityIndex end/start - 1): {REALIZED_RETURN_PCT:.4f}%")
    print(f"gap (daily-sampled average - realized): {gap_pp:.4f} percentage points")

    os.makedirs(os.path.dirname(CHART_PATH), exist_ok=True)
    daily_dates = pd.to_datetime(daily["date"])

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.step(
        raw["datetime"],
        raw["apy"],
        where="post",
        label="Full-resolution rate (every event, true duration)",
        color="#a0aec0",
        linewidth=0.5,
        zorder=1,
        rasterized=True,
    )
    ax.plot(
        daily_dates,
        daily["liquidityRate"],
        label="Daily-sampled APY (one snapshot/day, naively averaged)",
        color="#2b6cb0",
        linewidth=1.3,
        zorder=2,
    )
    ax.axhline(
        REALIZED_RETURN_PCT,
        color="#c53030",
        linestyle="--",
        linewidth=1.6,
        label=f"Realized return over window ({REALIZED_RETURN_PCT:.2f}%)",
        zorder=3,
    )
    ax.set_title("Aave v3 USDC: daily-sampled APY vs. full-resolution rate vs. realized return")
    ax.set_xlabel("Date")
    ax.set_ylabel("APY (%)")
    ax.legend(loc="upper left", fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(CHART_PATH, dpi=150)
    print(f"wrote chart to {CHART_PATH}")


if __name__ == "__main__":
    main()

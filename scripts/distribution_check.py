"""Test the simpler explanation before reaching for a selection story: is the daily-series
overstatement just heavy tails (a handful of extreme days) plus equal per-day weighting?
Also quantifies how much real time the rate actually spent above 8%, at full resolution."""
import os

import pandas as pd

RAW_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "usdc_raw_events.csv")
DAILY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "usdc_daily_rates.csv")

RAY = 10**27
SECONDS_PER_YEAR = 31536000
HIGH_RATE_THRESHOLD_PCT = 8.0


def liquidity_rate_to_apy_pct(raw_liquidity_rate):
    apr = int(raw_liquidity_rate) / RAY
    apy = (1 + apr / SECONDS_PER_YEAR) ** SECONDS_PER_YEAR - 1
    return apy * 100


def main():
    daily = pd.read_csv(DAILY_PATH)
    raw = pd.read_csv(RAW_PATH).sort_values("timestamp").reset_index(drop=True)
    raw["apy"] = raw["liquidityRate"].apply(liquidity_rate_to_apy_pct)
    raw["datetime"] = pd.to_datetime(raw["timestamp"], unit="s", utc=True)

    print("--- daily series (366 points) ---")
    print(f"min:    {daily['liquidityRate'].min():.4f}%")
    print(f"median: {daily['liquidityRate'].median():.4f}%")
    print(f"max:    {daily['liquidityRate'].max():.4f}%")
    print("top 10 daily values:")
    print(daily.nlargest(10, "liquidityRate")[["date", "liquidityRate"]].to_string(index=False))

    print()
    print(f"--- full event set ({len(raw)} points) ---")
    print(f"min:    {raw['apy'].min():.4f}%")
    print(f"median: {raw['apy'].median():.4f}%")
    print(f"max:    {raw['apy'].max():.4f}%")
    print("top 10 event values:")
    print(raw.nlargest(10, "apy")[["datetime", "apy"]].to_string(index=False))

    # How much real time did the rate actually spend above the threshold, at full resolution?
    dt = raw["timestamp"].diff().shift(-1).iloc[:-1]
    apy_held = raw["apy"].iloc[:-1]
    above = apy_held > HIGH_RATE_THRESHOLD_PCT
    hours_above = dt[above].sum() / 3600
    total_hours = dt.sum() / 3600

    print()
    print(f"--- time actually spent above {HIGH_RATE_THRESHOLD_PCT}% APY (full resolution) ---")
    print(f"hours above threshold: {hours_above:.1f} of {total_hours:.1f} total hours ({100 * hours_above / total_hours:.2f}% of the window)")
    print(f"in days: {hours_above / 24:.2f} of {total_hours / 24:.1f}")

    # How many of the 366 daily samples land above the threshold, for contrast.
    daily_above = (daily["liquidityRate"] > HIGH_RATE_THRESHOLD_PCT).sum()
    print(f"daily samples above threshold: {daily_above} of {len(daily)} ({100 * daily_above / len(daily):.2f}% of daily samples)")


if __name__ == "__main__":
    main()

"""Decompose the 1.99pp gap between naive daily-APY averaging and the true realized return
into: (a) daily-sampling artifact, (b) APY-vs-APR averaging convexity, (c) residual.

Definitive test: duration-weight the APR across all 892,803 raw events (weight = seconds
until the next event) and compound it the same way Aave's own linear-interest accrual does
(calculateLinearInterest, per aave/protocol-subgraphs/src/helpers/reserve-logic.ts). If that
reproduces the 3.6663% realized return from liquidityIndex, it validates the reconstruction
and everything else can be measured relative to it.
"""
import os
from datetime import datetime, timezone

import pandas as pd

RAW_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "usdc_raw_events.csv")
DAILY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "usdc_daily_rates.csv")

RAY = 10**27
SECONDS_PER_YEAR = 31536000
TRUE_REALIZED_PCT = (1.1820654587021906 / 1.140260048268024 - 1) * 100

WINDOW_START = int(datetime(2025, 8, 15, tzinfo=timezone.utc).timestamp())
WINDOW_END = int(datetime(2026, 8, 15, tzinfo=timezone.utc).timestamp())


def liquidity_rate_to_apy_pct(raw_liquidity_rate):
    apr = int(raw_liquidity_rate) / RAY
    apy = (1 + apr / SECONDS_PER_YEAR) ** SECONDS_PER_YEAR - 1
    return apy * 100


def duration_weighted_compound(timestamps, raw_liquidity_rates):
    """prod(1 + APR_i * dt_i / YEAR) - 1, dt_i = time to next event. Mirrors Aave's own
    linear-interest-per-period accrual, so this is the same operation liquidityIndex performs."""
    ratio = 1.0
    for i in range(len(timestamps) - 1):
        apr = int(raw_liquidity_rates[i]) / RAY
        dt = timestamps[i + 1] - timestamps[i]
        ratio *= 1 + apr * dt / SECONDS_PER_YEAR
    return (ratio - 1) * 100


def nearest_to_fixed_clock_series(raw):
    """One row per day: the event closest to that day's 00:00 UTC, picked over the whole
    timestamp range (not restricted to events dated that calendar day). Unlike 'last event
    of the day', this doesn't prefer moments when transaction volume happens to be high."""
    timestamps = raw["timestamp"].to_numpy()
    n_days = (WINDOW_END - WINDOW_START) // 86400 + 1
    rows = []
    for i in range(n_days):
        target = WINDOW_START + i * 86400
        idx = timestamps.searchsorted(target)
        candidates = [j for j in (idx - 1, idx) if 0 <= j < len(timestamps)]
        best = min(candidates, key=lambda j: abs(int(timestamps[j]) - target))
        rows.append(raw.iloc[best])
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def main():
    raw = pd.read_csv(RAW_PATH).sort_values("timestamp").reset_index(drop=True)

    # (c) residual: full-resolution duration-weighted APR, compounded, vs the true realized
    # return computed directly from liquidityIndex.
    full_pct = duration_weighted_compound(raw["timestamp"].tolist(), raw["liquidityRate"].tolist())
    residual_pp = full_pct - TRUE_REALIZED_PCT

    # (a) sampling artifact: same duration-weighted-compounding methodology, but downsampled
    # to one event per UTC day (last observation of the day), same as the committed daily CSV.
    raw["date"] = pd.to_datetime(raw["timestamp"], unit="s", utc=True).dt.date
    daily_raw = raw.groupby("date", as_index=False).last().sort_values("timestamp").reset_index(drop=True)
    daily_ts = daily_raw["timestamp"].tolist()
    daily_rates_raw = daily_raw["liquidityRate"].tolist()
    daily_correct_pct = duration_weighted_compound(daily_ts, daily_rates_raw)
    sampling_pp = daily_correct_pct - full_pct

    # (b) convexity: same daily sample set, naive linear average of already-annualized APY
    # values (what was reported as the "time-weighted average advertised APY", 5.6590%)
    # instead of duration-weighted compounding of the underlying APR.
    daily_csv = pd.read_csv(DAILY_PATH)
    dates = pd.to_datetime(daily_csv["date"])
    weights = (dates.shift(-1) - dates).dt.days.iloc[:-1]
    rates = daily_csv["liquidityRate"].iloc[:-1]
    naive_avg_pct = (rates * weights).sum() / weights.sum()
    convexity_pp = naive_avg_pct - daily_correct_pct

    total_pp = naive_avg_pct - TRUE_REALIZED_PCT

    print(f"true realized return (liquidityIndex end/start - 1):        {TRUE_REALIZED_PCT:.4f}%")
    print(f"full-resolution duration-weighted APR, compounded:          {full_pct:.4f}%")
    print(f"daily-resolution duration-weighted APR, compounded:         {daily_correct_pct:.4f}%")
    print(f"naive average of daily APY values:                          {naive_avg_pct:.4f}%")
    print()
    print(f"(c) residual (full-resolution reconstruction vs true):      {residual_pp:+.4f} pp")
    print(f"(a) sampling artifact (daily vs full resolution):           {sampling_pp:+.4f} pp")
    print(f"(b) convexity (naive APY average vs correct compounding):   {convexity_pp:+.4f} pp")
    print(f"    sum of (a)+(b)+(c):                                     {sampling_pp + convexity_pp + residual_pp:+.4f} pp")
    print(f"    total gap (naive average vs true realized):             {total_pp:+.4f} pp")

    # Mechanism test: is "last event of the day" biased toward spikes because spikes generate
    # more transactions? Compare against a fixed-clock sample (event nearest 00:00 UTC each
    # day) built with the same duration-weighted-compounding methodology.
    print()
    print("--- mechanism test: event-density selection vs fixed-clock sampling ---")
    fixed_clock = nearest_to_fixed_clock_series(raw)
    fixed_clock_pct = duration_weighted_compound(fixed_clock["timestamp"].tolist(), fixed_clock["liquidityRate"].tolist())
    fixed_clock_gap_pp = fixed_clock_pct - full_pct

    print(f"last-event-of-day series, compounded:                       {daily_correct_pct:.4f}%  (gap vs full-res: {sampling_pp:+.4f} pp)")
    print(f"nearest-to-00:00-UTC series, compounded:                    {fixed_clock_pct:.4f}%  (gap vs full-res: {fixed_clock_gap_pp:+.4f} pp)")
    if abs(fixed_clock_gap_pp) < abs(sampling_pp):
        print("fixed-clock sampling is closer to full-resolution -> consistent with event-density selection bias")
    else:
        print("fixed-clock sampling is NOT closer to full-resolution -> event-density selection is not the mechanism")

    # What a user glancing at the frontend at a random moment typically sees (median, over
    # events) vs what they'd actually earn (duration-weighted mean, over time).
    print()
    print("--- full event set: glance vs. earn ---")
    apy_values = raw["liquidityRate"].apply(liquidity_rate_to_apy_pct)
    median_apy = apy_values.median()

    dt = raw["timestamp"].diff().shift(-1)
    dt = dt.iloc[:-1]
    weighted_apy = apy_values.iloc[:-1]
    duration_weighted_mean_apy = (weighted_apy * dt).sum() / dt.sum()

    print(f"median rate across all {len(raw)} events:                        {median_apy:.4f}%")
    print(f"duration-weighted mean rate across the window:              {duration_weighted_mean_apy:.4f}%")


if __name__ == "__main__":
    main()

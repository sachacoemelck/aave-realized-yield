I set out to show that the APY DeFi protocols advertise is higher than what a lender actually earns. Over a year of USDC on Aave v3, I measured a gap of two percentage points: 5.66% advertised against 3.67% realized. Then I checked where the gap came from, and 95% of it turned out to be my own measurement, not Aave's number.

This note is about that mistake, because it is not mine alone. It comes from sampling a rate once a day, the way almost every yield dashboard, backtest and comparison table I have seen is built.

**The headline**

Over the same window, a daily series that samples the deposit rate once a day, the way almost every dashboard and backtest does, reads above 8% on 89 of 366 days: 24.3% of the year. The actual rate, measured at every one of the 892,803 rate-update events that happened over that year, was above 8% for 2.34% of the time. A tenfold overstatement of how much time was spent at elevated rates.

**Why**

The mechanism is simple once you look for it: Aave's deposit rate is spiky and upward-skewed. It sits low most of the time and occasionally jumps, briefly, to a much higher level before falling back. A once-a-day sample has no way to distinguish "elevated for five minutes" from "elevated for the whole day": whichever event it happens to catch gets frozen and stretched across the 24 hours it didn't actually occupy.

That single mechanism accounts for the entire two-point gap I originally reported. Decomposed:

- 1.89 percentage points: the sampling artifact above, daily snapshots versus the full event set.
- 0.10 percentage points: a smaller, separate effect, averaging already-annualized APY values linearly instead of duration-weighting the underlying rate before annualizing. APY is a convex function of the simple rate, so a naive average of APYs overstates the equivalent APY of the average rate.
- 0.002 percentage points: residual, essentially rounding.

**The validation**

Here is the check that makes the decomposition trustworthy rather than merely plausible. `liquidityIndex`, the number Aave's contracts use to track cumulative interest, is literally the time integral of the deposit rate; it only moves when the rate does, and only by the amount of time that rate was in force. So if you take every one of the 892,803 rate-update events, weight each one's rate by the seconds until the next event, and compound them exactly the way Aave's own contracts do, you should reconstruct the same growth in `liquidityIndex` that actually happened.

It does: the reconstruction lands within 0.0018 percentage points of the realized return computed directly from `liquidityIndex`. That is not a rough agreement, it is the same number, computed two different ways. It closes the loop: the full-resolution event set and the protocol's own accounting agree, so the daily series is the thing that's wrong, not the other way around.

**Data quality, a smaller finding worth flagging**

While chasing this down I checked Aave's own subgraph data at the timestamps of the largest spikes, and found its `utilizationRate` field reporting values above 100%, which is not possible; a pool cannot lend out more than it holds. The field is computed from two balances that don't update on the same schedule (one continuously rebases for accrued interest, the other only moves when someone transacts), and under sustained stress they drift far enough apart to produce an impossible number. A second, independently-derived utilization figure I'd built from the same underlying balances was worse, not better: off by roughly three times as much. Neither should be trusted at high utilization. I ended up inferring the true utilization by inverting Aave's own interest rate curve from the rate it actually charged, which doesn't depend on either broken balance.

**What stays open**

That inversion is where the honest gap is. The implied utilization at all three spike events I checked sits at the same value to four decimal places: 93.1%, wherever I looked, months apart. That kind of consistency looks like a hard constraint, not an emergent equilibrium, so I checked the obvious candidate: Aave halts new borrowing once a reserve hits its configured borrow cap, which would freeze utilization exactly like this. It doesn't hold up: debt was nowhere near the cap at the first spike, and the cap itself changed between spikes. I have ruled out the mechanisms I could think to test. I have not found the one that's actually pinning it at 93.1%.

The headline number was never the problem. Aave publishes a rate that, measured properly, matches what it pays almost exactly: a duration-weighted reconstruction across 892,803 events lands within 0.0018 points of the realized return. The protocol does what it says.

What fails is the measurement. A daily series reads above 8% on a quarter of the year; the rate was actually there 2% of the time. Anyone sizing an allocation from that series overstates the yield by two points, and two points on a large book is not a rounding error.

Three things I would take from this. Sample a rate by the time it holds, not by the day it falls on. Treat published fields as claims, not facts: Aave's own subgraph reports utilisation above 100%, which cannot happen. And when a result confirms what you expected, that is the moment to attack it hardest: this one did, and it was wrong.

I could not settle why the rate pins at 93.1% utilisation. Two mechanisms were tested and rejected; saturation stands by elimination, not by proof. The code is public, and I would rather be corrected than quoted.

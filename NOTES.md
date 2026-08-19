# Open questions

## 1. Reserve-id leak in the full fetch — closed

The `or` clause in `fetch_daily_rates.py` repeats `reserve`/`timestamp_gte` inside each
branch to avoid a top-level-sibling ambiguity in graph-node's filter handling. The full
paginated fetch (891,932 rows across ~892 pages) that produced `data/usdc_daily_rates.csv`
never had this check run directly against it — the two attempts to re-run the full fetch
with the check included both failed before completing (one read timeout, one killed
externally) — so instead of re-fetching, `scripts/probe_reserve_leak.py` ran the same `or`
clause as three independent single pages (`first: 1000`, no full pagination): the start of
the window, the middle of the window, and the most recent 1000 rows (end of the window). All
three came back with exactly one distinct `reserve.id`, matching the expected USDC reserve.

This doesn't prove every one of the 891,932 rows is clean — only that the clause behaves
correctly at three points spread across the window, with no sign of the sibling-condition
ambiguity that motivated the rewrite. Treating this as sufficient evidence the clause isn't
leaking, given the where clause itself doesn't change behavior based on position in the
result set — it's the same repeated-condition filter evaluated fresh each page. Considering
this question closed without a full re-fetch.

## 2. totalLiquidity / totalDebt vs utilizationRate — plausible but untested explanation

`totalDebt / totalLiquidity` diverges from the subgraph's own `utilizationRate` field, and the
gap grows roughly monotonically over the year (~0.04 near the start of the window to ~0.22 near
the end). Working theory: `totalCurrentVariableDebt` is rebased every event via
`rayMul(totalScaledVariableDebt, variableBorrowIndex)`, while `totalLiquidity`/
`availableLiquidity` are only adjusted by raw transfer amounts on balance-changing events and
never rebased for interest accrued in between — so `utilizationRate`, computed by the subgraph
from the latter pair, stays internally self-consistent while our recombination of a rebased
numerator over a stale denominator drifts. This is inferred from reading
`aave/protocol-subgraphs` mapping source, not confirmed against any external ground truth
(e.g. on-chain reserve state at matching block heights). Doesn't affect `liquidityIndex` (which
is rebased the same way `totalCurrentVariableDebt` is) or the realized-return calculation.

**Still open, deliberately deferred.** True on-chain ground truth would need an archive RPC
(state at a block ~months old) — free public endpoints (`ethereum-rpc.publicnode.com`,
`1rpc.io`, `eth.llamarpc.com`, `rpc.ankr.com`, `cloudflare-eth.com`) either gate archive
calls behind a paid token or don't retain the history. DeFiLlama's `poolsBorrow` endpoint,
which would give an independent totalSupply/totalBorrow split (and therefore utilization),
also turned out to require their paid API plan — their free `pools`/`chart` endpoints only
expose `tvlUsd` and `apy`, no borrow-side or utilization data. Decided not to pursue either
(no new sign-ups) since utilization only feeds the planned $1m-position extension of this
project, not the current main result — leaving it open and documented rather than resolved.
Revisit if/when that extension is in scope.

## 3. liquidityRate → APY conversion — cross-checked against DeFiLlama, holds up

Unlike utilization, DeFiLlama's free `chart` endpoint for the Aave v3 Ethereum USDC pool
(`aa70268e-4b52-42bf-a116-608b370f9501`) does expose `apyBase`, an independently computed
base supply APY. This is the number the main result actually depends on (`liquidityRate` →
APY, via the RAY→APR→APY conversion documented in the README/commit history), so it was
checked instead of utilization. Compared at the same three dates:

| date | DeFiLlama apyBase | our liquidityRate (APY) |
|---|---|---|
| 2025-08-15 | 4.3713% | 4.4375% |
| 2026-02-14 | 2.3566% | 2.4972% |
| 2026-08-15 | 3.3026% | 3.3251% |

Differences are small (0.02–0.14 percentage points) and consistent with snapshot-timing
differences (DeFiLlama samples ~23:01 UTC; our daily rows take the last update of the UTC
calendar day) rather than a conversion error. Treating the RAY→APR→APY conversion chain as
validated by an independent source.

## 4. The 1.99pp "advertised vs. realized" gap was mostly our own measurement error, not a property of Aave's rate

**Framing note, important:** the finding below is not "Aave's advertised APY overstates what
depositors actually earn." It's that a naive daily-average of Aave's advertised APY, computed
by us from once-a-day snapshots, overstated it — and that overstatement is a defect in that
specific measurement, not a property of the rate Aave actually advertises. At full temporal
resolution, advertised and realized track almost exactly (see below). Do not cite the 1.99pp
figure as evidence Aave over-advertises.

**Definitive test.** `scripts/decompose_gap.py` duration-weights the APR across all 892,803
raw `ReserveParamsHistoryItem` events for the window (`data/usdc_raw_events.csv`, fetched by
`scripts/fetch_raw_events.py`) — each event's rate held for the seconds until the next event —
and compounds it exactly the way Aave's own linear-interest accrual does
(`calculateLinearInterest` in `aave/protocol-subgraphs`). Result: **3.6681%**, against a true
realized return of **3.6663%** from `liquidityIndex` directly — a residual of **+0.0018pp**.
That's the validation: this reconstruction is doing the same arithmetic the protocol does, so
everything else can be measured as a deviation from it.

Decomposing the originally-reported 1.9927pp gap (naive average of 366 daily-snapshot APY
values, 5.6590%, vs. true realized 3.6663%) against that full-resolution baseline:

| component | pp |
|---|---|
| (a) daily-sampling artifact (366 daily snapshots vs. all 892,803 events) | +1.8944 |
| (b) convexity (averaging already-annualized APY vs. duration-weighting the underlying APR) | +0.0965 |
| (c) residual (reconstruction vs. true realized) | +0.0018 |
| **sum** | **+1.9927** (= the full original gap) |

**~95% of the gap is (a): a defect in how we sampled our own daily series, not in the number
Aave advertises.**

**Mechanism test — hypothesis rejected.** Working theory going in: "last event of the day" is
not a fixed clock time — rate spikes generate more transactions, so the last event of a day is
disproportionately likely to fall inside a spike window, biasing the daily series upward. To
test it, `scripts/decompose_gap.py::nearest_to_fixed_clock_series` builds an alternative daily
series using the event closest to a fixed 00:00 UTC each day (a selection rule with no
relationship to transaction density) and compounds it the same way.

| series | compounded return | gap vs. full-resolution |
|---|---|---|
| last event of the day | 5.5625% | +1.8944 pp |
| nearest to 00:00 UTC | 5.5748% | +1.9066 pp |

The fixed-clock series is not closer to full-resolution — it's marginally *further*. **This
rejects the event-density-selection hypothesis.** Whatever drives the daily-sampling artifact,
it isn't which specific event within a day gets picked; both a density-biased rule and a
density-blind rule produce essentially the same ~1.9pp overstatement.

**Mechanism confirmed — heavy tails plus equal per-day weighting, no selection story needed.**
`scripts/distribution_check.py` tested the simpler explanation directly: how much real time
did the rate actually spend above 8% APY, at full resolution, versus how many of the 366
daily samples read above 8%?

| | above 8% APY |
|---|---|
| full resolution (892,803 events, duration-weighted) | 204.6 hours = **8.52 real days** of 365 (2.34% of the window) |
| daily series | **89 of 366 days** (24.3%) |

A ~10x inflation. The top-10 full-resolution readings confirm why: the single highest value
(13.4282%) occurs as a tight cluster of events between 07:59 and 11:26 UTC on 2026-04-19 — a
few hours, not days. But the daily series shows 2026-04-19, 04-20, *and* 04-21 all sitting
near that same peak, because each of those days' one-sample-per-day pick landed after a brief
spike and froze it as that whole day's rate. Heavy-tailed, brief transient spikes combined
with flat 1-day weighting in the naive daily method fully explains the artifact; the earlier
"asymmetric transitions" guess (below, struck through) is unnecessary and was never confirmed.

~~Candidate explanation, untested: the chart (`charts/apy_vs_realized.png`) shows rate regimes
that jump up sharply and decay slowly (sawtooth shape)...~~ — **superseded.** Retracting this.
It also relied on a chart description ("sustained 10-13% regime from April 2026 onward") that
was itself wrong — see next paragraph.

**Correction: there is no sustained high-rate regime.** The chart was described earlier as
showing a "sustained 10-13% regime from April 2026 onward." That characterization came from
reading the biased daily series and does not hold at full resolution — real exposure above 8%
totals 8.52 days across the entire year, scattered across brief episodes (hours each), not a
multi-week plateau. `charts/apy_vs_realized.png` should be read with that caveat, or
regenerated from the full-resolution series before being used to describe rate behavior.

**Glance vs. earn, from the full event set** (`liquidityRate` converted to APY per event):
- Median rate across all 892,803 events: **3.4667%**
- Duration-weighted mean rate across the window: **3.6799%**

Both are close to the true realized return (3.6663%) and nowhere near the daily-sampled
5.66%. This confirms the artifact is specific to *once-daily temporal* sampling — event-level
statistics (median over all events, or the correctly duration-weighted mean) are well-behaved
on their own. A depositor who happened to check the Aave frontend at a uniformly random moment
would, on average, see something close to what they actually earned; the distortion only shows
up when that check is compressed to one sample per day and then naively averaged.

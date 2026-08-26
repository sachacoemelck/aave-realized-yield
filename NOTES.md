# Open questions

## 1. Reserve-id leak in the full fetch: closed

The `or` clause in `fetch_daily_rates.py` repeats `reserve`/`timestamp_gte` inside each
branch to avoid a top-level-sibling ambiguity in graph-node's filter handling. The full
paginated fetch (891,932 rows across ~892 pages) that produced `data/usdc_daily_rates.csv`
never had this check run directly against it. The two attempts to re-run the full fetch
with the check included both failed before completing (one read timeout, one killed
externally), so instead of re-fetching, `scripts/probe_reserve_leak.py` ran the same `or`
clause as three independent single pages (`first: 1000`, no full pagination): the start of
the window, the middle of the window, and the most recent 1000 rows (end of the window). All
three came back with exactly one distinct `reserve.id`, matching the expected USDC reserve.

This doesn't prove every one of the 891,932 rows is clean, only that the clause behaves
correctly at three points spread across the window, with no sign of the sibling-condition
ambiguity that motivated the rewrite. Treating this as sufficient evidence the clause isn't
leaking, given the where clause itself doesn't change behavior based on position in the
result set: it's the same repeated-condition filter evaluated fresh each page. Considering
this question closed without a full re-fetch.

## 2. totalLiquidity / totalDebt vs utilizationRate: plausible but untested explanation

`totalDebt / totalLiquidity` diverges from the subgraph's own `utilizationRate` field, and the
gap grows roughly monotonically over the year (~0.04 near the start of the window to ~0.22 near
the end). Working theory: `totalCurrentVariableDebt` is rebased every event via
`rayMul(totalScaledVariableDebt, variableBorrowIndex)`, while `totalLiquidity`/
`availableLiquidity` are only adjusted by raw transfer amounts on balance-changing events and
never rebased for interest accrued in between, so `utilizationRate`, computed by the subgraph
from the latter pair, stays internally self-consistent while our recombination of a rebased
numerator over a stale denominator drifts. This is inferred from reading
`aave/protocol-subgraphs` mapping source, not confirmed against any external ground truth
(e.g. on-chain reserve state at matching block heights). Doesn't affect `liquidityIndex` (which
is rebased the same way `totalCurrentVariableDebt` is) or the realized-return calculation.

**Still open, deliberately deferred.** True on-chain ground truth would need an archive RPC
(state at a block ~months old); free public endpoints (`ethereum-rpc.publicnode.com`,
`1rpc.io`, `eth.llamarpc.com`, `rpc.ankr.com`, `cloudflare-eth.com`) either gate archive
calls behind a paid token or don't retain the history. DeFiLlama's `poolsBorrow` endpoint,
which would give an independent totalSupply/totalBorrow split (and therefore utilization),
also turned out to require their paid API plan; their free `pools`/`chart` endpoints only
expose `tvlUsd` and `apy`, no borrow-side or utilization data. Decided not to pursue either
(no new sign-ups) since utilization only feeds the planned $1m-position extension of this
project, not the current main result; it's left open and documented rather than resolved.
Revisit if/when that extension is in scope.

**Update, see §5:** curve inversion (independent of both `totalLiquidity` and
`availableLiquidity`, so unaffected by the staleness described above) gives a trustworthy
utilization estimate at three saturation events, and neither liquidity-derived measure comes
close to it: not just our derived value, the subgraph's own `utilizationRate` field too.
This sharpens the open question rather than resolving it: both measures are unreliable at
high utilization, to different degrees.

## 3. liquidityRate → APY conversion: cross-checked against DeFiLlama, holds up

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
by us from once-a-day snapshots, overstated it, and that overstatement is a defect in that
specific measurement, not a property of the rate Aave actually advertises. At full temporal
resolution, advertised and realized track almost exactly (see below). Do not cite the 1.99pp
figure as evidence Aave over-advertises.

**Definitive test.** `scripts/decompose_gap.py` duration-weights the APR across all 892,803
raw `ReserveParamsHistoryItem` events for the window (`data/usdc_raw_events.csv`, fetched by
`scripts/fetch_raw_events.py`), each event's rate held for the seconds until the next event,
and compounds it exactly the way Aave's own linear-interest accrual does
(`calculateLinearInterest` in `aave/protocol-subgraphs`). Result: **3.6681%**, against a true
realized return of **3.6663%** from `liquidityIndex` directly: a residual of **+0.0018pp**.
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

**Mechanism test, hypothesis rejected.** Working theory going in: "last event of the day" is
not a fixed clock time; rate spikes generate more transactions, so the last event of a day is
disproportionately likely to fall inside a spike window, biasing the daily series upward. To
test it, `scripts/decompose_gap.py::nearest_to_fixed_clock_series` builds an alternative daily
series using the event closest to a fixed 00:00 UTC each day (a selection rule with no
relationship to transaction density) and compounds it the same way.

| series | compounded return | gap vs. full-resolution |
|---|---|---|
| last event of the day | 5.5625% | +1.8944 pp |
| nearest to 00:00 UTC | 5.5748% | +1.9066 pp |

The fixed-clock series is not closer to full-resolution; it's marginally *further*. **This
rejects the event-density-selection hypothesis.** Whatever drives the daily-sampling artifact,
it isn't which specific event within a day gets picked; both a density-biased rule and a
density-blind rule produce essentially the same ~1.9pp overstatement.

**Mechanism confirmed: heavy tails plus equal per-day weighting, no selection story needed.**
`scripts/distribution_check.py` tested the simpler explanation directly: how much real time
did the rate actually spend above 8% APY, at full resolution, versus how many of the 366
daily samples read above 8%?

| | above 8% APY |
|---|---|
| full resolution (892,803 events, duration-weighted) | 204.6 hours = **8.52 real days** of the 366-day window (2.34%) |
| daily series | **89 of 366 days** (24.3%) |

A ~10x inflation. The top-10 full-resolution readings confirm why: the single highest value
(13.4282%) occurs as a tight cluster of events between 07:59 and 11:26 UTC on 2026-04-19;
a few hours, not days. But the daily series shows 2026-04-19, 04-20, *and* 04-21 all sitting
near that same peak, because each of those days' one-sample-per-day pick landed after a brief
spike and froze it as that whole day's rate. Heavy-tailed, brief transient spikes combined
with flat 1-day weighting in the naive daily method fully explains the artifact; the earlier
"asymmetric transitions" guess (below, struck through) is unnecessary and was never confirmed.

~~Candidate explanation, untested: the chart (`charts/apy_vs_realized.png`) shows rate regimes
that jump up sharply and decay slowly (sawtooth shape)...~~ **Superseded.** Retracting this.
It also relied on a chart description ("sustained 10-13% regime from April 2026 onward") that
was itself wrong; see next paragraph.

**Correction: there is no sustained high-rate regime.** The chart was described earlier as
showing a "sustained 10-13% regime from April 2026 onward." That characterization came from
reading the biased daily series and does not hold at full resolution. Real exposure above 8%
totals 8.52 days across the entire year, scattered across brief episodes (hours each), not a
multi-week plateau. `charts/apy_vs_realized.png` should be read with that caveat, or
regenerated from the full-resolution series before being used to describe rate behavior.

**Glance vs. earn, from the full event set** (`liquidityRate` converted to APY per event):
- Median rate across all 892,803 events: **3.4667%**
- Duration-weighted mean rate across the window: **3.6799%**

Both are close to the true realized return (3.6663%) and nowhere near the daily-sampled
5.66%. This confirms the artifact is specific to *once-daily temporal* sampling; event-level
statistics (median over all events, or the correctly duration-weighted mean) are well-behaved
on their own. A depositor who happened to check the Aave frontend at a uniformly random moment
would, on average, see something close to what they actually earned; the distortion only shows
up when that check is compressed to one sample per day and then naively averaged.

## 5. The finding, stated plainly, plus curve-saturation verification

**Lead finding:** the daily series reads above 8% APY on 89 of 366 days (24.3% of days
sampled). At full resolution, the rate was actually above 8% for only 2.34% of the window
(204.6 of 8,760 hours, 8.52 real days). **The daily-sampling method overstates time spent at
elevated rates by roughly tenfold.** That tenfold gap is the finding, not the 1.99pp headline
number, which is a downstream artifact of it.

**Caveat, kept because it's more accurate and harder to attack:** that 8.52 days isn't 110
uniformly brief blips. `scripts/distribution_check.py` breaks the above-8% time into 110
distinct episodes; the median is 43 minutes, but three episodes account for ~67% of the
total: 95.6 hours (~4 days), 32.8 hours (~1.4 days), and 8.2 hours. The true picture is a few
genuinely multi-day elevated stretches plus a long tail of brief recurring spikes, not a clean
"everything is a blip" story. The daily-sampling overstatement holds either way, but claiming
uniform brevity would be an easy target.

**Curve-saturation check.** The top daily values cluster tightly around ~13.427% APY across
dates months apart (2025-08 through 2026-08), not the kind of value a noisy, unbounded
process would produce repeatedly. Checked whether this is the reserve's rate curve
saturating, using the USDC reserve's actual interest-rate-strategy parameters (queried from
the subgraph's `Reserve` entity, historical `block: { number: N }` queries against blocks
located via header-only binary search, no archive RPC needed, since block *headers* are
retained by any full node even though historical *state* isn't):

- `optimalUtilisationRate` = 92%, `variableRateSlope1` = 5.5%, `variableRateSlope2` = 60%,
  `baseVariableBorrowRate` = 0%, `reserveFactor` = 10%; unchanged between the historical
  blocks checked and today, so no rate-curve governance change during the window.

Checked the reserve's state at the exact timestamp of the daily peak on three separate dates
months apart (2026-04-19, 2026-07-09, 2026-08-01). Two different rates, labeled explicitly
since juxtaposing them without labels reads as an inconsistency when it isn't one:
`variableBorrowRate` is what **borrowers pay**, a linear/simple annual rate (APR), a direct
output of the rate-strategy curve. `liquidityRate` is what **suppliers earn**, derived from
the borrow side (`≈ variableBorrowRate × utilization × (1 − reserveFactor)`) and reported here
as a compounded annual rate (APY, same RAY→APR→APY conversion used throughout this project).
They are different quantities in different conventions, not two views of the same number.

| date | `utilizationRate` (subgraph field) | `variableBorrowRate` (borrow APR, linear) | `liquidityRate` (supply APY, compounded) |
|---|---|---|---|
| 2026-04-19 07:59:23 UTC | 1.010714 | 0.140000 | 13.4282% |
| 2026-07-09 23:58:35 UTC | 1.015259 | 0.139947 | 13.4222% |
| 2026-08-01 23:54:35 UTC | 1.015512 | 0.140000 | 13.4282% |

**Stop: the `utilizationRate` column above is impossible on its face** (>100%), and that's
the same failure mode NOTES.md #2 already flagged: `utilizationRate` is computed by the
subgraph as `1 − availableLiquidity/totalLiquidity`, and `totalLiquidity`/`availableLiquidity`
are event-driven raw balances that don't rebase for continuously accruing interest the way
`totalCurrentVariableDebt` does. Trusting this field here would have been trusting the same
broken input NOTES.md #2 already distrusted, not new evidence, a repeat of the same mistake.

**Inverted instead.** `variableBorrowRate` is a direct, self-consistent output of the rate
strategy contract; it doesn't depend on `totalLiquidity`/`availableLiquidity` at all. Solving
the two-kink curve backwards (`u = optimal + (variableBorrowRate − base − slope1) × (1 − optimal) / slope2`)
for the utilization that would have produced the observed rate, and comparing that against
*both* liquidity-derived measures (`scripts/invert_curve.py`):

| date | implied utilization (curve inversion) | subgraph `utilizationRate` | our derived `totalDebt / totalLiquidity` |
|---|---|---|---|
| 2026-04-19 | 0.931333 | 1.010714 | 1.165885 |
| 2026-07-09 | 0.931326 | 1.015259 | 1.235973 |
| 2026-08-01 | 0.931333 | 1.015512 | 1.242401 |

**Not the outcome hypothesized, and more useful for it.** The plan was: if implied utilization
matches the subgraph's own field, that field is right and our derived value is wrong, question
settled. It doesn't match. Implied utilization is a sane, plausible number (~93.1%, just above
the 92% optimal kink, consistent, to four figures, across three dates months apart) and
**neither liquidity-derived measure comes close**: the subgraph's own field overshoots by
~8-9pp (still impossible, >100%) and our derived ratio overshoots by ~30-31pp (impossible by a
wider margin, consistent with NOTES.md #2's finding that our derived value runs even further
from reality than the subgraph's own field, growing worse over time).

**What this settles and what it doesn't.** Settled: the spikes are the curve saturating;
the implied utilization sits just past the optimal kink, essentially identical across three
independent occurrences months apart, which is the signature of a real recurring ceiling
condition, not noise. **Not settled the way NOTES.md #2 hoped:** this isn't "subgraph field
right, derived value wrong". Both liquidity-derived utilization measures break down under
sustained high-utilization stress, the subgraph's own field less severely than our derived
one but still past the impossible 100% mark. Curve inversion, not either liquidity-based
measure, is the reliable estimate of utilization at these moments. NOTES.md #2 stays open;
this sharpens rather than resolves it.

**Final test: is it actually a borrowCap hard stop, not curve saturation?** Six-figure
identical implied utilization across dates months apart looks less like an emergent
equilibrium and more like a hard constraint. Aave v3 halts new borrowing once `totalDebt`
reaches the reserve's `borrowCap`. If that's what's happening, utilization would freeze and
the rate would pin, for a cleaner reason than "the curve happens to saturate here." The
subgraph tracks `borrowCap` directly on `Reserve` (config data, not a rebasing balance, so
this comparison doesn't inherit the `totalLiquidity` staleness problem either way). Checked
`totalDebt` (`totalCurrentVariableDebt + totalPrincipalStableDebt`, the properly-rebased side,
not the stale one) against `borrowCap` at the same three timestamps:

| date | borrowCap | totalDebt | totalDebt / borrowCap |
|---|---|---|---|
| 2026-04-19 | $7,000,000,000 | $2,466,797,939 | 35.2% |
| 2026-07-09 | $2,250,000,000 | $1,956,422,941 | 87.0% |
| 2026-08-01 | $2,250,000,000 | $1,941,179,046 | 86.3% |

**Rejected.** `borrowCap` was cut from $7B to $2.25B by governance sometime between the first
and second spike, so it isn't even the same constraint across dates, and at no point is
`totalDebt` at or near the cap (35% in April is nowhere close; 86-87% in July/August is
elevated but well short of a hard stop). Borrowing was not halted by the cap at any of these
three moments. This rules out the borrowCap-freeze mechanism and leaves the rate-curve
saturation explanation (§5, curve inversion) as the standing, now further corroborated,
account of the spikes, corroborated by elimination specifically, not by direct confirmation
of what caps the curve at exactly ~93.1% utilization each time. That residual specific
question (why 93.1%, not some other point past the 92% kink) remains open.

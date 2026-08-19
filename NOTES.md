# Open questions

## 1. Reserve-id leak in the full fetch — unverified

The `or` clause in `fetch_daily_rates.py` repeats `reserve`/`timestamp_gte` inside each
branch to avoid a top-level-sibling ambiguity in graph-node's filter handling. A lightweight
probe (`scripts/probe_reserve_leak.py`, single page, `first: 1000`) found only the expected
USDC reserve id in the first 1000 rows. The full paginated fetch (891,932 rows across ~892
pages) that produced `data/usdc_daily_rates.csv` has not had this check run against it — the
two attempts to re-run the full fetch with the check included both failed before completing
(one read timeout, one killed externally). The committed CSV predates the check entirely.

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

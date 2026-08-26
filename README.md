Realized vs. advertised yield on Aave v3
Question

How much of the advertised deposit APY does an allocator actually capture over a full year, and where does the gap come from?

Scope
Market: USDC, Aave v3, Ethereum mainnet
Window: 365 days
Simulated position: $1,000,000
Why these choices

Aave is the deepest lending market in DeFi, with the longest usable history: if realized yield diverges from advertised APY here, it diverges everywhere. One year, because deposit rates move with the cycle and a shorter window would only capture a single rate regime. $1m, because that is the size at which the position starts moving the utilisation rate itself, which is the question a small fund actually faces.

Result

A year of USDC on Aave v3 (Ethereum mainnet): a naive daily-sampled average of the advertised
APY (5.66%) versus the realized return computed from Aave's own `liquidityIndex` (3.67%) shows
a 1.99-percentage-point gap. Decomposed, 95% of that gap (1.89pp) is a sampling artifact — one
snapshot per UTC day catches Aave's brief, upward-skewed rate spikes far out of proportion to
how long they actually lasted: 89 of 366 daily samples read above 8% APY, while the rate was
actually above 8% for only 2.34% of the year — a tenfold overstatement. A further 0.10pp is a
convexity effect from averaging annualized APY values instead of duration-weighting the
underlying rate before annualizing. The residual is 0.002pp.

Validation: duration-weighting the rate across all 892,803 rate-update events in the window
and compounding it the way Aave's contracts do reproduces the realized `liquidityIndex` return
to within 0.0018pp — confirming the advertised rate and what depositors actually earn track
almost exactly, once measured correctly. The gap was in the measurement, not the protocol.

Along the way: Aave's own subgraph reports utilization above 100% at high-stress moments,
which is impossible; both it and a derived alternative are unreliable there. Inverting Aave's
interest rate curve from the observed rate gives a trustworthy utilization estimate (~93.1%,
consistent across three separate spike events months apart) — but why it pins there
specifically is unresolved; a borrow-cap hard-stop was tested and ruled out.

Full methodology, data-quality caveats, and dead ends: see `NOTES.md`.

Disclosure

I hold a position on Aave. This analysis tests whether that position is justified; the result is published either way.

Exploratory research. Not audited, not investment advice.

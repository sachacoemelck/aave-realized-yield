"""Utilization above 100% is impossible. Rather than trust either liquidity-derived utilization
measure (the subgraph's own utilizationRate field, or our own derived totalDebt/totalLiquidity
— both ultimately built on totalLiquidity/availableLiquidity, which NOTES.md #2 already showed
drift from reality), invert the interest rate curve: the observed variableBorrowRate is a
direct, self-consistent output of the reserve's rate strategy contract at the time it was set,
independent of the totalLiquidity staleness issue. Solve the two-kink curve backwards for the
utilization it implies, then compare that against both liquidity-derived measures."""
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

RPC = "https://ethereum-rpc.publicnode.com"
API_KEY = os.environ["THEGRAPH_API_KEY"]
ENDPOINT = f"https://gateway.thegraph.com/api/{API_KEY}/subgraphs/id/Cd2gEDVeqnjBn1hSeqFMitw8Q1iiyV9FYUZkLNRcL87g"
USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"

RAY = 10**27
OPTIMAL = 0.92
SLOPE1 = 0.055
SLOPE2 = 0.6
BASE = 0.0

SPIKES = [
    ("2026-04-19", datetime(2026, 4, 19, 7, 59, 23, tzinfo=timezone.utc)),
    ("2026-07-09", datetime(2026, 7, 9, 23, 58, 35, tzinfo=timezone.utc)),
    ("2026-08-01", datetime(2026, 8, 1, 23, 54, 35, tzinfo=timezone.utc)),
]


def rpc_call(method, params):
    r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
    return r.json()["result"]


def block_timestamp(n):
    return int(rpc_call("eth_getBlockByNumber", [hex(n), False])["timestamp"], 16)


def find_block(target_ts):
    latest = int(rpc_call("eth_blockNumber", []), 16)
    low, high = 0, latest
    while low < high:
        mid = (low + high) // 2
        if block_timestamp(mid) < target_ts:
            low = mid + 1
        else:
            high = mid
    return low


def implied_utilization(variable_borrow_rate_apr):
    """Invert base + slope1 + (u - optimal)/(1 - optimal) * slope2 = rate, for u > optimal."""
    return OPTIMAL + (variable_borrow_rate_apr - BASE - SLOPE1) * (1 - OPTIMAL) / SLOPE2


def get_reserve_at_block(block):
    gql = """
    query($underlyingAsset: Bytes!, $block: Int!) {
      reserves(where: { underlyingAsset: $underlyingAsset }, block: { number: $block }) {
        variableBorrowRate
        utilizationRate
        totalLiquidity
        totalCurrentVariableDebt
        totalPrincipalStableDebt
        decimals
      }
    }
    """
    r = requests.post(
        ENDPOINT,
        json={"query": gql, "variables": {"underlyingAsset": USDC_ADDRESS, "block": block}},
        timeout=30,
    ).json()
    return r["data"]["reserves"][0]


def main():
    print(f"curve params: base={BASE}, slope1={SLOPE1}, slope2={SLOPE2}, optimal={OPTIMAL}")
    print()
    header = f"{'date':<12}{'variableBorrowRate (APR)':>26}{'implied util.':>16}{'subgraph utilizationRate':>26}{'derived totalDebt/totalLiquidity':>34}"
    print(header)

    for label, dt in SPIKES:
        block = find_block(int(dt.timestamp()))
        reserve = get_reserve_at_block(block)

        vbr = int(reserve["variableBorrowRate"]) / RAY
        implied_u = implied_utilization(vbr)
        subgraph_u = float(reserve["utilizationRate"])

        total_debt = int(reserve["totalCurrentVariableDebt"]) + int(reserve["totalPrincipalStableDebt"])
        total_liquidity = int(reserve["totalLiquidity"])
        derived_u = total_debt / total_liquidity if total_liquidity else float("nan")

        print(f"{label:<12}{vbr:>26.6f}{implied_u:>16.6f}{subgraph_u:>26.6f}{derived_u:>34.6f}")


if __name__ == "__main__":
    main()

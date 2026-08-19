"""Pull the daily USDC deposit rate on Aave v3 Ethereum from the Aave subgraph."""
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["THEGRAPH_API_KEY"]
SUBGRAPH_ID = "Cd2gEDVeqnjBn1hSeqFMitw8Q1iiyV9FYUZkLNRcL87g"  # Aave V3 Ethereum
ENDPOINT = f"https://gateway.thegraph.com/api/{API_KEY}/subgraphs/id/{SUBGRAPH_ID}"

USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WINDOW_DAYS = 365
PAGE_SIZE = 1000
RAY = 10**27
SECONDS_PER_YEAR = 31536000

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "usdc_daily_rates.csv")


def run_query(gql, variables, max_attempts=5):
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(ENDPOINT, json={"query": gql, "variables": variables}, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if "errors" in payload:
                raise RuntimeError(payload["errors"])
            return payload["data"]
        except (requests.exceptions.RequestException, RuntimeError):
            if attempt == max_attempts:
                raise
            time.sleep(2**attempt)


def get_usdc_reserve():
    gql = """
    query($underlyingAsset: Bytes!) {
      reserves(where: { underlyingAsset: $underlyingAsset }) {
        id
        symbol
        decimals
      }
    }
    """
    reserves = run_query(gql, {"underlyingAsset": USDC_ADDRESS})["reserves"]
    if len(reserves) != 1:
        raise RuntimeError(f"expected exactly one USDC reserve, got {len(reserves)}")
    return reserves[0]


def fetch_history_items(reserve_id, since_timestamp):
    gql = """
    query($reserve: String!, $since: Int!, $lastTimestamp: Int!, $lastId: String!, $pageSize: Int!) {
      reserveParamsHistoryItems(
        first: $pageSize
        orderBy: timestamp
        orderDirection: asc
        where: {
          or: [
            { reserve: $reserve, timestamp_gte: $since, timestamp_gt: $lastTimestamp }
            { reserve: $reserve, timestamp_gte: $since, timestamp: $lastTimestamp, id_gt: $lastId }
          ]
        }
      ) {
        id
        reserve {
          id
        }
        timestamp
        liquidityRate
        liquidityIndex
        utilizationRate
        totalLiquidity
        totalCurrentVariableDebt
        totalPrincipalStableDebt
      }
    }
    """
    items = []
    last_timestamp = since_timestamp - 1
    last_id = ""
    while True:
        variables = {
            "reserve": reserve_id,
            "since": since_timestamp,
            "lastTimestamp": last_timestamp,
            "lastId": last_id,
            "pageSize": PAGE_SIZE,
        }
        page = run_query(gql, variables)["reserveParamsHistoryItems"]
        items.extend(page)
        if len(page) < PAGE_SIZE:
            break
        last_timestamp = int(page[-1]["timestamp"])
        last_id = page[-1]["id"]
        time.sleep(0.2)
    return items


def liquidity_rate_to_apy_pct(raw_liquidity_rate):
    apr = int(raw_liquidity_rate) / RAY
    apy = (1 + apr / SECONDS_PER_YEAR) ** SECONDS_PER_YEAR - 1
    return apy * 100


UTILIZATION_TOLERANCE = 1e-4


def check_utilization_consistency(df):
    nonzero = df[df["totalLiquidity"] > 0]
    computed = nonzero["totalDebt"] / nonzero["totalLiquidity"]
    diff = (computed - nonzero["utilizationRate"]).abs()
    bad = nonzero[diff > UTILIZATION_TOLERANCE]
    if not bad.empty:
        print(
            f"WARNING: {len(bad)} row(s) where totalDebt/totalLiquidity diverges from "
            f"utilizationRate by more than {UTILIZATION_TOLERANCE}:"
        )
        print(bad)


def check_single_reserve(items, expected_reserve_id):
    counts = pd.Series([item["reserve"]["id"] for item in items]).value_counts()
    print(f"distinct reserve.id values in raw fetch: {len(counts)}")
    print(counts)
    if len(counts) != 1 or counts.index[0] != expected_reserve_id:
        raise RuntimeError(
            "or clause leaked rows from other reserves into the fetch — aborting before any "
            "downstream processing"
        )


def main():
    reserve = get_usdc_reserve()
    decimals = reserve["decimals"]

    since = int((datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).timestamp())
    items = fetch_history_items(reserve["id"], since)

    check_single_reserve(items, reserve["id"])

    rows = []
    for item in items:
        total_debt = int(item["totalCurrentVariableDebt"]) + int(item["totalPrincipalStableDebt"])
        rows.append(
            {
                "timestamp": int(item["timestamp"]),
                "liquidityRate": liquidity_rate_to_apy_pct(item["liquidityRate"]),
                "liquidityIndex": int(item["liquidityIndex"]) / RAY,
                "utilizationRate": float(item["utilizationRate"]),
                "totalLiquidity": int(item["totalLiquidity"]) / 10**decimals,
                "totalDebt": total_debt / 10**decimals,
            }
        )

    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    check_utilization_consistency(df)

    df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.date
    daily = df.groupby("date", as_index=False).last()
    daily = daily[
        ["date", "liquidityRate", "liquidityIndex", "utilizationRate", "totalLiquidity", "totalDebt"]
    ]

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    daily.to_csv(OUTPUT_PATH, index=False)

    first_index = df["liquidityIndex"].iloc[0]
    last_index = df["liquidityIndex"].iloc[-1]
    realized_return = last_index / first_index - 1

    print(f"rows fetched: {len(df)}")
    print(f"distinct days covered: {len(daily)}")
    print(f"first liquidityIndex: {first_index}")
    print(f"last liquidityIndex: {last_index}")
    print(f"realized return over window: {realized_return * 100:.4f}%")
    print(f"wrote {len(daily)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

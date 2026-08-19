"""Lightweight check: does the paginated where clause in fetch_daily_rates.py leak rows
from other reserves? Three single pages (first: 1000, no full pagination): start of the
window, middle of the window, and the most recent 1000 rows (end of the window)."""
import os
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["THEGRAPH_API_KEY"]
SUBGRAPH_ID = "Cd2gEDVeqnjBn1hSeqFMitw8Q1iiyV9FYUZkLNRcL87g"  # Aave V3 Ethereum
ENDPOINT = f"https://gateway.thegraph.com/api/{API_KEY}/subgraphs/id/{SUBGRAPH_ID}"

USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def run_query(gql, variables):
    response = requests.post(ENDPOINT, json={"query": gql, "variables": variables}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def get_usdc_reserve():
    gql = """
    query($underlyingAsset: Bytes!) {
      reserves(where: { underlyingAsset: $underlyingAsset }) {
        id
      }
    }
    """
    reserves = run_query(gql, {"underlyingAsset": USDC_ADDRESS})["reserves"]
    if len(reserves) != 1:
        raise RuntimeError(f"expected exactly one USDC reserve, got {len(reserves)}")
    return reserves[0]


def probe(reserve_id, since_timestamp, order_direction="asc"):
    gql = """
    query($reserve: String!, $since: Int!, $lastTimestamp: Int!, $lastId: String!, $orderDirection: OrderDirection!) {
      reserveParamsHistoryItems(
        first: 1000
        orderBy: timestamp
        orderDirection: $orderDirection
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
      }
    }
    """
    variables = {
        "reserve": reserve_id,
        "since": since_timestamp,
        "lastTimestamp": since_timestamp - 1,
        "lastId": "",
        "orderDirection": order_direction,
    }
    return run_query(gql, variables)["reserveParamsHistoryItems"]


def check(label, reserve, items):
    counts = pd.Series([item["reserve"]["id"] for item in items]).value_counts()
    clean = len(counts) == 1 and counts.index[0] == reserve["id"]
    print(f"--- {label} ---")
    print(f"rows returned: {len(items)}")
    print(f"distinct reserve.id values: {len(counts)}")
    print(counts)
    print(f"clean: {clean}")
    return clean


def main():
    reserve = get_usdc_reserve()
    print(f"expected reserve.id: {reserve['id']}")

    window_start = int(datetime(2025, 8, 15, tzinfo=timezone.utc).timestamp())
    window_end = int(datetime(2026, 8, 15, tzinfo=timezone.utc).timestamp())
    window_mid = window_start + (window_end - window_start) // 2

    start_items = probe(reserve["id"], window_start, "asc")
    mid_items = probe(reserve["id"], window_mid, "asc")
    end_items = probe(reserve["id"], window_start, "desc")  # most recent 1000 in the window

    results = [
        check("start of window", reserve, start_items),
        check("middle of window", reserve, mid_items),
        check("end of window (most recent 1000)", reserve, end_items),
    ]
    print(f"all three pages clean: {all(results)}")


if __name__ == "__main__":
    main()

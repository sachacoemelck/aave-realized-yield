"""Lightweight check: does the paginated where clause in fetch_daily_rates.py leak rows
from other reserves? Single page, first: 1000, no pagination."""
import os
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


def probe(reserve_id, since_timestamp):
    gql = """
    query($reserve: String!, $since: Int!, $lastTimestamp: Int!, $lastId: String!) {
      reserveParamsHistoryItems(
        first: 1000
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
      }
    }
    """
    variables = {
        "reserve": reserve_id,
        "since": since_timestamp,
        "lastTimestamp": since_timestamp - 1,
        "lastId": "",
    }
    return run_query(gql, variables)["reserveParamsHistoryItems"]


def main():
    reserve = get_usdc_reserve()
    since = int((datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).timestamp())
    items = probe(reserve["id"], since)

    counts = pd.Series([item["reserve"]["id"] for item in items]).value_counts()
    print(f"rows returned: {len(items)}")
    print(f"expected reserve.id: {reserve['id']}")
    print(f"distinct reserve.id values: {len(counts)}")
    print(counts)


if __name__ == "__main__":
    main()

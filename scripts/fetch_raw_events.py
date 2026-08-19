"""Fetch every ReserveParamsHistoryItem for the USDC reserve in the window, raw, streamed to
disk page by page. Needed to duration-weight the APR across all events rather than one
daily snapshot; the daily-resampled CSV throws away the timing information required for that."""
import csv
import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["THEGRAPH_API_KEY"]
SUBGRAPH_ID = "Cd2gEDVeqnjBn1hSeqFMitw8Q1iiyV9FYUZkLNRcL87g"  # Aave V3 Ethereum
ENDPOINT = f"https://gateway.thegraph.com/api/{API_KEY}/subgraphs/id/{SUBGRAPH_ID}"

USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
PAGE_SIZE = 1000

WINDOW_START = int(datetime(2025, 8, 15, tzinfo=timezone.utc).timestamp())
WINDOW_END = int(datetime(2026, 8, 15, tzinfo=timezone.utc).timestamp())

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "usdc_raw_events.csv")
FIELDNAMES = ["id", "timestamp", "liquidityRate"]


def run_query(gql, variables, max_attempts=6):
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
      }
    }
    """
    reserves = run_query(gql, {"underlyingAsset": USDC_ADDRESS})["reserves"]
    if len(reserves) != 1:
        raise RuntimeError(f"expected exactly one USDC reserve, got {len(reserves)}")
    return reserves[0]


PAGE_GQL = """
query($reserve: String!, $since: Int!, $until: Int!, $lastTimestamp: Int!, $lastId: String!, $pageSize: Int!) {
  reserveParamsHistoryItems(
    first: $pageSize
    orderBy: timestamp
    orderDirection: asc
    where: {
      or: [
        { reserve: $reserve, timestamp_gte: $since, timestamp_lte: $until, timestamp_gt: $lastTimestamp }
        { reserve: $reserve, timestamp_gte: $since, timestamp_lte: $until, timestamp: $lastTimestamp, id_gt: $lastId }
      ]
    }
  ) {
    id
    reserve {
      id
    }
    timestamp
    liquidityRate
  }
}
"""


def main():
    reserve = get_usdc_reserve()
    print(f"reserve.id: {reserve['id']}")

    total = 0
    last_timestamp = WINDOW_START - 1
    last_id = ""

    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

        while True:
            variables = {
                "reserve": reserve["id"],
                "since": WINDOW_START,
                "until": WINDOW_END,
                "lastTimestamp": last_timestamp,
                "lastId": last_id,
                "pageSize": PAGE_SIZE,
            }
            page = run_query(PAGE_GQL, variables)["reserveParamsHistoryItems"]
            if not page:
                break

            bad = [item for item in page if item["reserve"]["id"] != reserve["id"]]
            if bad:
                raise RuntimeError(f"reserve leak: {len(bad)} rows from other reserves in this page")

            for item in page:
                writer.writerow(
                    {"id": item["id"], "timestamp": item["timestamp"], "liquidityRate": item["liquidityRate"]}
                )
            f.flush()

            total += len(page)
            last_timestamp = int(page[-1]["timestamp"])
            last_id = page[-1]["id"]
            print(f"fetched {total} rows, last timestamp {last_timestamp}")

            if len(page) < PAGE_SIZE:
                break
            time.sleep(0.2)

    print(f"done: {total} rows written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Quick connectivity check — fetches page 1 of 2024 declarations and prints
the first 3 declaration IDs. Run from repo root:

    python scripts/test_api_connectivity.py

To test against a mirror API:

    python scripts/test_api_connectivity.py --api-base-url https://declarations.com.ua/api/v2
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.ingestion.client import NazkClient


async def main(api_base_url: str) -> int:
    """Returns 0 on success, 1 on failure."""
    print(f"Target API : {api_base_url}")
    print("Fetching page 1 of 2024 declarations...")

    try:
        async with NazkClient(base_url=api_base_url) as client:
            result = await client.search_declarations(declaration_year=2024, page=1)
    except Exception as exc:
        print(f"\n[FAIL] Request raised an exception: {exc}")
        return 1

    items = result.get("items", result.get("data", []))
    total = result.get("total", result.get("count", "?"))

    print(f"Got {len(items)} items on page 1 (API reports total={total})")

    if not items:
        print("\n[WARN] Got HTTP 200 but empty items list — check API params / endpoint path.")
        return 1

    for item in items[:3]:
        doc_id  = item.get("id") or item.get("doc_id") or "?"
        ptype   = item.get("post_type", "?")
        pcat    = item.get("post_category", "?")
        year    = item.get("declaration_year", "?")
        print(f"  - id={doc_id}  post_type={ptype}  post_category={pcat}  year={year}")

    print("\nConnectivity OK ✓")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test NAZK API connectivity")
    parser.add_argument(
        "--api-base-url",
        type=str,
        default=settings.nazk_api_base_url,
        help="API base URL to test (default: settings.nazk_api_base_url)",
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args.api_base_url)))

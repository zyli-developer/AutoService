"""CLI: mint an API key for a general-bot tenant.

Usage: python scripts/issue_general_bot_key.py <tenant_id> [--label LABEL]

Prints the raw key to stdout (once — never stored). Appends the hash to
.autoservice/sandbox/<tenant_id>/api_keys.json.
"""
from __future__ import annotations

import argparse
import sys

from autoservice.integrations.general_bot.auth import issue_key


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue a general-bot API key")
    parser.add_argument("tenant_id")
    parser.add_argument("--label", default="", help="human-readable label")
    args = parser.parse_args()

    raw, key_id = issue_key(args.tenant_id, label=args.label)
    print(f"key_id: {key_id}")
    print(f"raw key (save now, will not be shown again): {raw}")
    print()
    print("Configure CINNOX (or other platform) with:")
    print(f"  Authorization: Bearer {raw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Read exactly one versioned neutral envelope from stdin; emit one JSON response."""
import json
import sys

sys.dont_write_bytecode = True

from _portable import response


def main():
    try:
        envelope = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        result = {"ok": False, "error": {"code": "invalid_json", "message": "Expected one JSON envelope"}}
    else:
        result = response(envelope)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

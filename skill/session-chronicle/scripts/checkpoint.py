#!/usr/bin/env python3
"""Persist pending evidence without a model; failures leave batches retryable."""
import json
import os
import sys

from _checkpoint import checkpoint
from _docsroot import resolve_base


if __name__ == "__main__":
    try:
        print(json.dumps(checkpoint(resolve_base(os.environ.get("PROJECT_ROOT") or os.getcwd()))))
    except Exception as error:
        print(f"session-chronicle: checkpoint failed ({type(error).__name__}); evidence retained", file=sys.stderr)
        sys.exit(1)

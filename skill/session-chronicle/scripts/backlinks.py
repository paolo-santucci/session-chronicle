#!/usr/bin/env python3
"""List session wikilinks and source provenance for a canonical topic."""
import argparse
import json
import sys

from _topic_graph import TopicGraph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--base", default=".")
    parser.add_argument("--count", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    graph = TopicGraph(args.base, include_evidence=False)
    graph.require_resolvable()
    canonical = graph.resolve(args.slug)
    hits = graph.supporting_sessions(canonical)
    if args.json:
        print(json.dumps({"slug": args.slug, "canonical_slug": canonical, "count": len(hits), "sessions": hits}))
    elif args.count:
        print(len(hits))
    else:
        print("\n".join(hits), end="\n" if hits else "")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)

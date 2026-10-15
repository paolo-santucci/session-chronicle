#!/usr/bin/env python3
"""Complete read-only inventory and structural validation; never applies changes."""
import argparse
import json
import os
import sys

from _docsroot import resolve_base
from _topic_graph import TopicGraph, REVIEW_NOTICE, body_links, string_list


def inventory(graph):
    records = []
    for path, note in sorted(graph.records.items()):
        fields = note["fields"]
        record_type = "topic" if path.relative_to(graph.base).parts[0] == "topics" else "session"
        records.append({
            "path": os.path.relpath(path, graph.project), "sha256": note["sha256"], "type": record_type,
            "record-kind": fields.get("record-kind", "legacy"), "note-kind": fields.get("note-kind"),
            "identity": fields.get("session-id") or fields.get("id") or path.stem,
            "id": fields.get("id"), "slug": path.stem, "session-id": fields.get("session-id"),
            "title": fields.get("title"), "status": fields.get("status"),
            "provenance": fields.get("provenance"), "sources": string_list(fields, "sources"),
            "aliases": string_list(fields, "aliases"), "links": string_list(fields, "links"),
            "body_links": sorted(body_links(note["body"])) if fields.get("record-kind") != "factual-evidence" else [],
            "redirects-to": fields.get("redirects-to"),
        })
    topics = sum(record["type"] == "topic" for record in records)
    return {"records": records, "unreadable": graph.unreadable,
            "coverage": {"discovered": len(records) + len(graph.unreadable), "readable": len(records),
                         "unreadable": len(graph.unreadable), "topics": topics, "sessions": len(records) - topics}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "validate"))
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    graph = TopicGraph(resolve_base(args.project), args.project)
    findings = graph.quality()
    result = {"findings": findings, "semantic_review_required": True, "review_notice": REVIEW_NOTICE}
    if args.command == "inventory":
        result.update(inventory(graph))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(bool(graph.unreadable) or (args.command == "validate" and any(
        item["severity"] == "error" for item in findings)))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error), "semantic_review_required": True}))
        sys.exit(2)

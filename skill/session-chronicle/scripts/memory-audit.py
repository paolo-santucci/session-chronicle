#!/usr/bin/env python3
"""Read-only graph audit; recurrence is distinct session identity, not file count."""
import argparse
import datetime
import json
import sys

from _topic_graph import TopicGraph, REVIEW_NOTICE, RESOLUTION_CODES, body_links, string_list, valid_slug


def stem(slug):
    for suffix in ("ies", "es", "s"):
        if slug.endswith(suffix) and len(slug) - len(suffix) >= 4:
            return slug[:-len(suffix)]
    return slug


def dangling_sessions(graph):
    counts = {}
    for links in graph.session_links().values():
        for link in links:
            if valid_slug(link) and graph.resolve(link) not in graph.topics:
                counts[link] = counts.get(link, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def orphan_topics(graph):
    inbound = set()
    for slug, note in graph.topics.items():
        for link in body_links(note["body"]):
            if valid_slug(link):
                target = graph.resolve(link)
                if target != slug:
                    inbound.add(target)
        inbound.update(graph.source_topics(slug) - {slug})
        if graph.supporting_sessions(slug):
            inbound.add(slug)
    return sorted(set(graph.topics) - inbound)


def duplicate_topics(graph):
    groups = {}
    for slug, note in graph.topics.items():
        for name in [slug] + string_list(note["fields"], "aliases"):
            groups.setdefault(stem(name), set()).add(slug)
    return sorted(sorted(group) for group in groups.values() if len(group) > 1)


def audit(args):
    graph = TopicGraph(args.base, include_evidence=False)
    quality = graph.quality()
    result = {}
    if args.quality:
        result.update(quality=quality, semantic_review_required=True, review_notice=REVIEW_NOTICE)
    modes = (args.orphans, args.dups, args.dangling, args.materialization_candidates, args.stale, args.quality)
    all_modes = not any(modes)
    if all_modes or any(modes[:-1]):
        errors = [item for item in quality if item["code"] in RESOLUTION_CODES]
        if errors:
            raise ValueError("Invalid topic graph: " + "; ".join(item["message"] for item in errors))
    if all_modes or args.orphans:
        result["orphans"] = orphan_topics(graph)
    if all_modes or args.dups:
        result["dups"] = duplicate_topics(graph)
    if all_modes or args.dangling:
        result["dangling"] = dangling_sessions(graph)
        result["broken_topic_edges"] = [item for item in quality if item["code"] == "broken-topic-edge"]
    if all_modes or args.materialization_candidates:
        result["materialization_candidates"] = sorted(link for link, count in dangling_sessions(graph).items()
                                                      if count >= args.threshold)
        result["_threshold"] = args.threshold
    if all_modes or args.stale:
        stale = []
        for slug, note in graph.topics.items():
            try:
                updated = datetime.date.fromisoformat(note["fields"].get("updated", ""))
                if (datetime.date.today() - updated).days > args.days:
                    stale.append(slug)
            except (TypeError, ValueError):
                continue
        result.update(stale=sorted(stale), _stale_days=args.days)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for mode in ("orphans", "dups", "dangling", "materialization-candidates", "stale", "quality", "json"):
        parser.add_argument("--" + mode, action="store_true")
    parser.add_argument("--base", default=".")
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    result = audit(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for key, value in result.items():
            if not key.startswith("_"):
                print(f"== {key} ==\n{json.dumps(value, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)

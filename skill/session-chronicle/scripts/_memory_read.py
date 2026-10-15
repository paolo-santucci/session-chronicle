"""Graph-aware recall and bounded startup topic orientation."""
import argparse
import datetime
import os
import sys

from _docsroot import resolve_base, orphan_warning
from _topic_graph import TopicGraph, active_topic


def recall(graph, slug, mode):
    graph.require_resolvable()
    canonical = graph.resolve(slug)
    if mode in ("--topic", "--all"):
        print(f"## [topic] {canonical}")
        note = graph.topics.get(canonical)
        if note:
            print(note["path"].read_text(encoding="utf-8"))
        else:
            print("(no topic note — subject not yet materialised)")
    if mode in ("--sessions", "--all"):
        print(f"\n## sessions supporting [[{canonical}]] (wikilinks and source provenance)")
        hits = graph.supporting_sessions(canonical)
        print("\n".join("- " + hit for hit in hits) if hits else "(none)")


def topic_index(graph):
    from _session_notes import print_recent_sessions
    print("## Project memory index (auto, read-only)")
    topics = [(slug, note) for slug, note in sorted(graph.topics.items()) if active_topic(note["fields"])]
    limit = max(0, int(os.environ.get("MEMORY_INDEX_MAX_TOPICS", "40")))
    print(f"### Topics ({len(topics)} active; {max(0, len(topics) - limit)} omitted)")
    for slug, note in topics[:limit]:
        title = note["fields"].get("title")
        print(f"- {slug}" + (f" — {title}" if title else ""))
    print("### Recent sessions (latest 8)")
    print_recent_sessions(graph.base, graph.session_views())
    health_summary(graph)
    print("_Recall full topic links and supporting sessions with memory_recall / memory-recall.sh <slug>; "
          "aliases, redirects and source provenance are resolved by the graph. "
          "Use topic-maintenance.py inventory --project PATH for the complete inventory._")


def health_summary(graph):
    stale = 0
    for note in graph.topics.values():
        try:
            updated = datetime.date.fromisoformat(note["fields"].get("updated", ""))
            stale += (datetime.date.today() - updated).days > 90
        except (TypeError, ValueError):
            continue
    dangling = {link for links in graph.session_links().values() for link in links if link not in graph.names}
    if stale > int(os.environ.get("MEMORY_HEALTH_STALE_MAX", "5")) or len(dangling) > int(
            os.environ.get("MEMORY_HEALTH_DANGLING_MAX", "10")):
        print(f"_Health: {stale} stale topic notes (>90d), {len(dangling)} forward-reference session links. "
              "Triage: memory-audit.py --quality --dangling --base <docs-root>_")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index")
    recall_parser = commands.add_parser("recall")
    recall_parser.add_argument("slug")
    modes = recall_parser.add_mutually_exclusive_group()
    for mode in ("--all", "--topic", "--sessions"):
        modes.add_argument(mode, dest="mode", action="store_const", const=mode)
    recall_parser.set_defaults(mode="--all")
    args = parser.parse_args()
    project = os.environ.get("PROJECT_ROOT") or os.getcwd()
    graph = TopicGraph(resolve_base(project), project, include_evidence=False)
    if args.command == "index":
        if not graph.records:
            warning = orphan_warning(project)
            if warning:
                print(warning)
            return
        topic_index(graph)
        return
    recall(graph, args.slug, args.mode)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)

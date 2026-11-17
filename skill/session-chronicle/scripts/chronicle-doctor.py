#!/usr/bin/env python3
"""One-command health check for a Chronicle project.

Answers the four questions an operator actually has, in one invocation:

1. Is the plugin installed, at which version, and is OpenCode loading it?
2. What is in the store (evidence, presentations, semantic summaries, topics)?
3. Will automatic retrieval still find the topic notes?
4. Is anything stuck (pending batches, non-empty drafts, audit findings)?

Read-only. Never writes, never contacts the network, never exits non-zero for a
degraded state unless --strict is passed, so it is safe to run in any project
and from any script.

Exit codes: 0 healthy, 1 degraded, 2 not loaded, 3 invalid docs-root.
With --strict, any non-healthy verdict exits non-zero; without it the command
always exits 0 and the verdict is on stdout.

stdlib only (no PyYAML): must never fail on a project that would otherwise work.
"""
import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _docsroot import detect_orphan, resolve  # noqa: E402
from _session_notes import select_candidates  # noqa: E402
from _topic_graph import parse_fields, read_frontmatter  # noqa: E402


def rel(path, project):
    try:
        return str(Path(path).relative_to(project))
    except ValueError:
        return str(path)


def count_by_kind(directory):
    """Record-kind / note-kind histogram. Undecodable notes are counted, not dropped."""
    counts = {}
    unreadable = 0
    for path in sorted(glob.glob(os.path.join(directory, "*.md"))):
        try:
            Path(path).read_bytes().decode("utf-8")
            fields = parse_fields(read_frontmatter(path))
        except (OSError, UnicodeError, ValueError):
            unreadable += 1
            continue
        kind = fields.get("record-kind") or fields.get("note-kind") or "legacy"
        if isinstance(kind, list):
            kind = kind[0] if kind else "legacy"
        counts[kind] = counts.get(kind, 0) + 1
    return counts, unreadable


def installation(project):
    """Version and ownership signals from both install routes."""
    result = {"module_version": None, "marker": False, "portable_entry": False, "loaded": False, "loaded_by": None}
    module = project / ".opencode" / "session-chronicle"
    manifest = module / "package.json"
    if manifest.is_file():
        try:
            result["module_version"] = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            pass
    result["marker"] = (module / ".session-chronicle-install.json").is_file()

    shim = project / ".opencode" / "plugins" / "session-chronicle.ts"
    entry = project / ".opencode" / "plugins" / "session-chronicle" / "index.ts"
    result["portable_entry"] = entry.is_file()
    if shim.is_file():
        result["loaded"], result["loaded_by"] = True, rel(shim, project)
    elif entry.is_file():
        result["loaded"], result["loaded_by"] = True, rel(entry, project)
    return result


def retrieval_window(project, base):
    """Reports retrieval's own candidate list through the shared selector."""
    files = glob.glob(os.path.join(base, "sessions", "*.md")) + glob.glob(os.path.join(base, "topics", "*.md"))
    files.sort(key=lambda path: os.path.getmtime(path) if os.path.exists(path) else 0.0, reverse=True)
    headers = []
    for path in files:
        try:
            headers.append((path, read_frontmatter(path)))
        except (OSError, UnicodeError, ValueError):
            # An unreadable note is not a candidate; retrieval raises instead, but the doctor's
            # job is to keep reporting the rest of the store.
            continue
    topics, sessions = [], []
    for path in select_candidates(headers, base)["eligible"]:
        (topics if "/topics/" in path.replace("\\", "/") else sessions).append(path)
    # retrieve-inject.py gives topics the first slots of the scan budget.
    cap = int(os.environ.get("MEMORY_INJECT_MAX_SCAN", "60"))
    return {
        "cap": cap,
        "eligible_sessions": len(sessions),
        "topics": len(topics),
        "topics_out_of_window": max(0, len(topics) - cap),
        "note": "Topics take the first scan slots; sessions fill the remainder.",
    }


def drafts(base):
    draft_dir = os.path.join(base, ".drafts")
    pending_dir = os.path.join(draft_dir, "pending")
    pending = len(glob.glob(os.path.join(pending_dir, "*.jsonl")))
    live, empty = [], []
    for path in sorted(glob.glob(os.path.join(draft_dir, "*.draft.jsonl"))):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        (live if size > 0 else empty).append({"path": os.path.basename(path), "bytes": size})
    return {"pending_batches": pending, "drafts_with_content": live, "empty_drafts": len(empty)}


def audit(base):
    try:
        import importlib.util

        module_path = Path(__file__).with_name("memory-audit.py")
        spec = importlib.util.spec_from_file_location("memory_audit", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return {"available": False, "findings": None}
    try:
        class Args:
            orphans = dups = dangling = stale = False
            materialization_candidates = False
            quality = True
            threshold = 2
            days = 90

        args = Args()
        args.base = base
        report = module.audit(args)
        qualities = report.get("quality", []) if isinstance(report, dict) else []
        return {"available": True, "findings": len(qualities),
                "by_code": sorted({item.get("code") for item in qualities if isinstance(item, dict)})}
    except Exception:
        return {"available": False, "findings": None}


def inspect(project, with_audit=True):
    report = {"project": str(project), "docs_root": None, "declared_by": None,
              "problems": [], "warnings": [], "notes": []}
    try:
        base, source = resolve(project)
    except ValueError as error:
        report["problems"].append(f"invalid docs-root: {error}")
        report["verdict"] = "invalid docs-root"
        report["code"] = 3
        return report

    report["docs_root"] = rel(base, project)
    report["declared_by"] = source
    report["exists"] = Path(base).is_dir()
    report["install"] = installation(project)

    try:
        orphan_base, _, orphans = detect_orphan(project)
        if orphans:
            report["warnings"].append(
                f"{len(orphans)} chronicle note(s) exist outside the resolved docs-root; "
                "capture and guards are writing somewhere you are not reading")
    except Exception:
        pass

    session_counts, unreadable_sessions = count_by_kind(os.path.join(base, "sessions"))
    topic_counts, unreadable_topics = count_by_kind(os.path.join(base, "topics"))
    report["sessions"] = {"by_kind": session_counts, "unreadable": unreadable_sessions,
                          "total": sum(session_counts.values()) + unreadable_sessions}
    report["topics"] = {"by_kind": topic_counts, "unreadable": unreadable_topics,
                        "legacy": topic_counts.get("legacy", 0),
                        "total": sum(topic_counts.values()) + unreadable_topics}

    newest = sorted(glob.glob(os.path.join(base, "sessions", "*.md")),
                    key=lambda path: os.path.getmtime(path), reverse=True)
    report["last_capture"] = None
    if newest:
        report["last_capture"] = {
            "note": os.path.basename(newest[0]),
            "age_days": round((time.time() - os.path.getmtime(newest[0])) / 86400, 1),
        }

    report["retrieval"] = retrieval_window(project, base)
    report["drafts"] = drafts(base)
    if with_audit:
        report["audit"] = audit(base)
    else:
        report["audit"] = {"available": False, "findings": None}

    report.update(verdicts(report))
    return report


def verdicts(report):
    problems, warnings, notes = report["problems"], report["warnings"], report["notes"]
    install = report["install"]

    if not install["loaded"]:
        problems.append("no OpenCode plugin entry under .opencode/plugins/; this project captures nothing")
    if install["module_version"] is None and not install["portable_entry"]:
        problems.append("no Chronicle module installed")
    if not report["exists"]:
        problems.append("docs-root directory does not exist; run a session or bootstrap once")
    if report["sessions"]["total"] == 0 and report["topics"]["total"] == 0 and report["exists"]:
        notes.append("installed and ready; no memory captured yet")

    if report["topics"]["legacy"]:
        warnings.append(f"{report['topics']['legacy']} topic note(s) predate note-kind; run /session-chronicle-refactor")
    if report["sessions"]["by_kind"].get("semantic-summary", 0) == 0 and report["sessions"]["total"] > 0:
        warnings.append("no semantic summaries; retrieval can only surface observed activity, never conclusions")
    if report["drafts"]["pending_batches"]:
        problems.append(f"{report['drafts']['pending_batches']} sealed batch(es) awaiting publication")
    if report["drafts"]["drafts_with_content"]:
        warnings.append(f"{len(report['drafts']['drafts_with_content'])} draft file(s) hold unpublished evidence")
    findings = report["audit"].get("findings")
    if findings:
        warnings.append(f"{findings} structural audit finding(s); review with memory_audit mode=quality")

    if problems:
        return {"verdict": "not loaded" if not install["loaded"] or install["module_version"] is None else "degraded",
                "code": 2 if not install["loaded"] or install["module_version"] is None else 1}
    if warnings:
        return {"verdict": "degraded", "code": 1}
    return {"verdict": "healthy", "code": 0}


def render(report):
    lines = [f"Chronicle doctor — {report['project']}"]
    if report.get("problems") and report["verdict"] == "invalid docs-root":
        for problem in report["problems"]:
            lines.append(f"  problem  {problem}")
        return "\n".join(lines)

    root = report["docs_root"] + (f" (declared in {report['declared_by']})" if report["declared_by"] else " (default)")
    lines.append(f"  docs-root  {root}")
    install = report["install"]
    loaded = "yes via " + install["loaded_by"] if install["loaded"] else "NO"
    version = install["module_version"] or ("portable 0.2.1" if install["portable_entry"] else "missing")
    lines.append(f"  install    {version}, marker={'yes' if install['marker'] else 'no'}, loaded={loaded}")

    sessions, topics = report["sessions"], report["topics"]
    kinds = ", ".join(f"{name}={count}" for name, count in sorted(sessions["by_kind"].items())) or "none"
    lines.append(f"  sessions   {sessions['total']} ({kinds})")
    note_kinds = ", ".join(f"{name}={count}" for name, count in sorted(topics["by_kind"].items())) or "none"
    lines.append(f"  topics     {topics['total']} ({note_kinds})")

    window = report["retrieval"]
    lines.append(f"  retrieval  {window['topics']} topics + {window['eligible_sessions']} eligible sessions, "
                 f"cap {window['cap']} (topics first)")
    last = report["last_capture"]
    lines.append(f"  last note  {last['note']} ({last['age_days']}d ago)" if last else "  last note  none")

    drafts_info = report["drafts"]
    lines.append(f"  drafts     {len(drafts_info['drafts_with_content'])} with content, "
                 f"{drafts_info['empty_drafts']} empty, {drafts_info['pending_batches']} pending"
                 f" ({', '.join(d['path'] + ' ' + str(d['bytes']) + 'B' for d in drafts_info['drafts_with_content']) or 'none'})")

    audit_info = report["audit"]
    if audit_info["findings"] is None:
        lines.append("  audit      unavailable")
    else:
        lines.append(f"  audit      {audit_info['findings']} finding(s)"
                     + (f" [{', '.join(audit_info['by_code'])}]" if audit_info["by_code"] else ""))

    lines.append("")
    for problem in report["problems"]:
        lines.append(f"  PROBLEM  {problem}")
    for warning in report["warnings"]:
        lines.append(f"  warn     {warning}")
    for note in report["notes"]:
        lines.append(f"  note     {note}")
    lines.append(f"  verdict  {report['verdict'].upper()}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Report Chronicle health for one project.")
    parser.add_argument("--project", default=os.getcwd(), help="project root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--no-audit", action="store_true", help="skip the structural topic audit")
    parser.add_argument("--strict", action="store_true", help="exit non-zero on any non-healthy verdict")
    arguments = parser.parse_args()

    report = inspect(Path(arguments.project).resolve(), with_audit=not arguments.no_audit)
    if arguments.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    if arguments.strict:
        return report.get("code", 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

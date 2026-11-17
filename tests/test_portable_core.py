"""Neutral boundary, real-process replay/crash recovery, and shared guard regressions."""
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skill/session-chronicle/scripts"
SCHEMA = Path(__file__).resolve().parents[1] / "schemas/envelope.schema.json"
sys.path.insert(0, str(SCRIPTS))
import _checkpoint as store
import _memory_markers as markers
import _portable as core
import _topic_graph as topic_graph
from _guards import guarded_semantic_replace
from _identity import HARNESSES, canonical_identity, parse_identity
from _session_notes import note_lint
from _topic_graph import note_ref

try:
    import jsonschema
except ModuleNotFoundError as error:
    if error.name != "jsonschema":
        raise
    jsonschema = None


SESSION_CONTEXT = {"harness": "opencode", "session_id": "fixture-session",
                   "workspace": "/workspace/project", "role": "primary"}


def retrieve_envelope(arguments, context=None):
    return {"schema_version": 1, "operation": "retrieve",
            "context": dict(context or SESSION_CONTEXT), "arguments": arguments}


class PortableCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chronicle-core-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.base = self.project / "docs"
        (self.project / "AGENTS.md").write_text("---\ndocs-root: docs\n---\n")
        self.context = {"harness": "opencode", "session_id": "native-α:/same", "workspace": str(self.project), "role": "primary"}

    def envelope(self, operation, arguments=None, context=None):
        return {"schema_version": 1, "operation": operation, "context": context or self.context, "arguments": arguments or {}}

    def invoke(self, operation, arguments=None, context=None, env=None):
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "chronicle.py")],
                                input=json.dumps(self.envelope(operation, arguments, context)), text=True,
                                capture_output=True, env={**os.environ, **(env or {})}, timeout=20)
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode == 0, payload["ok"], result.stderr)
        self.assertEqual(result.stderr, "")
        return payload

    def success(self, operation, arguments=None, context=None, env=None):
        result = self.invoke(operation, arguments, context, env)
        self.assertTrue(result["ok"], result)
        return result["result"]

    def prompt(self, event="event-1", text="Octopus architecture", **changes):
        return dict(operation="prompt.submit", event_id=event, text=text, status="completed", origin="user", **changes)

    def records(self):
        records = []
        for path in (self.base / "sessions").glob("*--evidence-*.md"):
            records += note_lint.factual_records(path.read_text())
        return records

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def topic(self, slug="octopus", body="Octopus architecture is a user-stated observation."):
        return (f"---\nid: {slug}\ntype: topic\nnote-kind: atomic\ntitle: Octopus architecture\n"
                "status: active\ncreated: 2026-10-15\nupdated: 2026-10-15\nprovenance: stated_by_user\n"
                "aliases: []\nlinks: []\nsources: [AGENTS.md]\n---\n\n" + body + "\n")

    INJECTED_NEEDLES = (markers.PROJECT_MEMORY_PREFIX, "chronicle-untrusted")

    def injected_text(self):
        """The memory block a prompt carries today: real retrieval output, through `find`."""
        topics = self.base / "topics"
        topics.mkdir(parents=True, exist_ok=True)
        (topics / "octopus.md").write_text(self.topic())
        injected = self.success("find", {"query": "octopus"})
        self.assertIn(markers.PROJECT_MEMORY_PREFIX, injected)
        return injected

    def assert_no_injected_memory(self):
        """NFR-09 sweep: decoded records and every persisted byte carry no marker."""
        records = self.records()
        self.assertTrue(records, "the sweep must run on published evidence")
        for needle in self.INJECTED_NEEDLES:
            decoded = [record for record in records if needle in json.dumps(record, ensure_ascii=False)]
            self.assertFalse(decoded, needle)
            persisted = [path for path, data in self.snapshot().items() if needle.encode() in data]
            self.assertFalse(persisted, needle)

    def test_four_harnesses_and_unicode_ids_have_distinct_reversible_provenance(self):
        targets = set()
        for harness in HARNESSES:
            context = dict(self.context, harness=harness)
            self.success("capture", self.prompt(), context)
            state = self.success("context", context=context)
            targets.add(state["target"])
            self.assertEqual(parse_identity(state["session_id"]), state["identity"])
        self.assertEqual(len(targets), 4)
        self.assertEqual({record["identity"]["harness"] for record in self.records()}, set(HARNESSES))

    def test_identity_validation_rejects_mismatch_and_noncanonical_encoding_but_keeps_legacy(self):
        self.assertEqual(note_lint.record_session_id({"sessionID": "legacy-id"}), "legacy-id")
        identity = {"schema_version": 1, "harness": "pi", "session_id": "session"}
        qualified = canonical_identity(identity)
        for record in ({"session_id": qualified + "=", "identity": identity}, {"session_id": qualified, "identity": dict(identity, harness="codex")},
                       {"sessionID": "legacy", "event_id": "native"}, {"session_id": qualified, "sessionID": "other"}):
            with self.subTest(record=record), self.assertRaises(ValueError):
                note_lint.record_session_id(record)

    def test_workspace_context_ignores_environment_and_isolates_worktrees(self):
        second = self.project / "worktree"
        second.mkdir()
        other = dict(self.context, workspace=str(second))
        self.success("capture", self.prompt(text="First workspace"), env={"PROJECT_ROOT": str(second)})
        self.success("capture", self.prompt(text="Second workspace"), other, env={"PROJECT_ROOT": str(self.project)})
        self.success("checkpoint")
        self.success("checkpoint", context=other)
        self.assertEqual([record["text"] for record in self.records()], ["First workspace"])
        foreign = next((second / "docs/sessions").glob("*--evidence-*.md")).read_text()
        self.assertIn("Second workspace", foreign)
        self.assertNotIn("First workspace", foreign)

    def test_missing_or_unknown_runtime_provenance_never_mutates(self):
        baseline = self.snapshot()
        cases = [dict(self.context, role="unknown"), dict(self.context, session_id=""),
                 dict(self.context, harness="invented"), dict(self.context, workspace="."),
                 dict(self.context, workspace=str(self.project / "missing"))]
        cases += [{key: value for key, value in self.context.items() if key != removed} for removed in self.context]
        for context in cases:
            self.assertFalse(self.invoke("capture", self.prompt(), context)["ok"])
        self.assertEqual(self.snapshot(), baseline)

    def test_delegated_capture_and_checkpoint_skip_context_enrichment_blocks_reads_work(self):
        child = dict(self.context, role="delegated")
        self.assertEqual(self.success("capture", self.prompt(), child)["status"], "skipped")
        self.assertEqual(self.success("checkpoint", context=child)["status"], "skipped")
        self.assertFalse(self.invoke("context", context=child)["ok"])
        self.assertEqual(self.success("find", {"query": "octopus"}, child), "")
        self.assertFalse(self.base.exists())

    def test_unknown_role_can_read_all_memory_operations_but_cannot_mutate_memory(self):
        unknown = dict(self.context, harness="pi", role="unknown")
        reads = [("find", {"query": "octopus"}), ("recall", {"slug": "octopus"}),
                 ("backlinks", {"slug": "octopus"}), ("audit", {"mode": "quality"}), ("index", {})]
        for operation, arguments in reads:
            result = self.success(operation, arguments, unknown)
            if operation == "find":
                self.assertEqual(result, "")
            else:
                self.assertIn("<chronicle-untrusted>", result)
        for operation, arguments in (("capture", self.prompt()), ("checkpoint", {}), ("context", {}), ("continuation", {})):
            self.assertEqual(self.invoke(operation, arguments, unknown)["error"]["code"], "unknown_provenance")
        self.assertFalse(self.base.exists())

    def test_unknown_guard_allows_unrelated_source_replace_edit_and_patch_without_mutating(self):
        unknown = dict(self.context, harness="pi", role="unknown")
        source = self.project / "source.py"
        source.write_text("original source\n")
        before = self.snapshot()
        arguments = [{"kind": "replace", "path": "source.py", "content": "changed"},
                     {"kind": "edit", "path": "source.py", "old_text": "original", "new_text": "changed"},
                     {"kind": "patch", "patch": "*** Begin Patch\n*** Update File: source.py\n@@\n-original source\n+changed\n*** End Patch\n"}]
        for argument in arguments:
            self.assertTrue(self.success("guard", argument, unknown)["allowed"])
        self.assertEqual(self.snapshot(), before)

    def test_unknown_guard_blocks_memory_targets_aliases_and_mixed_patches(self):
        unknown = dict(self.context, harness="pi", role="unknown")
        (self.base / "topics").mkdir(parents=True)
        topic = self.base / "topics/octopus.md"
        topic.write_text(self.topic())
        (self.project / "alias.md").symlink_to(topic)
        os.link(topic, self.project / "hardlink.md")
        for path in ("docs/topics/octopus.md", "docs/sessions/new.md", "docs/.drafts/new.jsonl",
                     "docs/.drafts/pending/new.jsonl", "docs/pending/new.jsonl", "alias.md", "hardlink.md"):
            for arguments in ({"kind": "replace", "path": path, "content": "changed"},
                              {"kind": "edit", "path": path, "old_text": "Octopus", "new_text": "changed"}):
                self.assertEqual(self.invoke("guard", arguments, unknown)["error"]["code"], "unknown_provenance")
        mixed = "*** Begin Patch\n*** Add File: source.py\n+safe\n*** Add File: docs/topics/new.md\n+protected\n*** End Patch\n"
        self.assertEqual(self.invoke("guard", {"kind": "patch", "patch": mixed}, unknown)["error"]["code"], "unknown_provenance")

    def test_missing_stable_event_id_blocks_without_content_hash_fallback(self):
        for value in (None, "", "  ", 4):
            arguments = dict(self.prompt(), event_id=value)
            self.assertFalse(self.invoke("capture", arguments)["ok"])
        arguments.pop("event_id")
        self.assertFalse(self.invoke("capture", arguments)["ok"])
        self.assertFalse(self.base.exists())

    def test_same_text_distinct_events_survive_interleaving_checkpoint_and_restart(self):
        first, second = self.prompt("one"), self.prompt("two")
        self.success("capture", first)
        self.success("capture", self.prompt("other", "Intervening event"))
        self.assertEqual(self.success("capture", first)["status"], "duplicate")
        self.success("checkpoint")
        evidence = self.snapshot()
        self.assertEqual(self.success("capture", first)["status"], "duplicate")
        self.assertEqual(evidence, self.snapshot())
        self.success("capture", second)
        self.success("checkpoint")
        self.assertEqual(sorted(record["event_id"] for record in self.records()), ["one", "other", "two"])

    def test_reused_event_identity_conflict_is_visible_and_preserves_evidence(self):
        self.success("capture", self.prompt())
        self.success("checkpoint")
        before = self.snapshot()
        result = self.invoke("capture", self.prompt(text="Different admitted content"))
        self.assertEqual(result["error"]["code"], "event_conflict")
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_duplicate_unique_and_checkpoint_processes_lose_no_events(self):
        jobs = [("capture", self.prompt("duplicate")) for _ in range(6)]
        jobs += [("capture", self.prompt(f"unique-{index}")) for index in range(6)]
        jobs += [("checkpoint", {}) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda job: self.invoke(*job), jobs))
        self.assertTrue(all(result["ok"] for result in results), results)
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 7)
        self.assertEqual(len({record["event_id"] for record in self.records()}), 7)

    def crash(self, operation, arguments, hook):
        program = "import sys,os,json\nsys.path.insert(0," + repr(str(SCRIPTS)) + ")\nimport _checkpoint as store\nimport _portable as core\n" + hook + "\ncore.dispatch(json.load(sys.stdin))\n"
        result = subprocess.run([sys.executable, "-B", "-c", program],
                                input=json.dumps(self.envelope(operation, arguments)), text=True,
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_crash_before_atomic_capture_replace_leaves_accepted_history_and_retry_once(self):
        self.success("capture", self.prompt("existing"))
        self.crash("capture", self.prompt(), "store.os.replace=lambda *args: os._exit(77)")
        self.success("capture", self.prompt())
        self.success("checkpoint")
        self.assertEqual({record["event_id"] for record in self.records()}, {"existing", "event-1"})

    def test_crash_after_atomic_capture_replace_is_deduplicated_on_restart(self):
        self.crash("capture", self.prompt(),
                   "original=store.os.replace\ndef fail(*args):\n original(*args)\n os._exit(77)\nstore.os.replace=fail")
        self.assertEqual(self.success("capture", self.prompt())["status"], "duplicate")
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 1)

    def test_crash_after_pending_rename_retains_event_identity_for_replay(self):
        self.success("capture", self.prompt())
        self.crash("checkpoint", {},
                   "original=store.Path.rename\ndef fail(self,*args):\n original(self,*args)\n os._exit(77)\nstore.Path.rename=fail")
        self.assertEqual(self.success("capture", self.prompt())["status"], "duplicate")
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 1)

    def test_crash_after_evidence_publication_recovers_pending_without_duplicate(self):
        self.success("capture", self.prompt())
        self.crash("checkpoint", {},
                   "original=store.os.link\ndef fail(*args):\n original(*args)\n os._exit(77)\nstore.os.link=fail")
        self.assertEqual(self.success("capture", self.prompt())["status"], "duplicate")
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(list((self.base / ".drafts/pending").glob("*.jsonl")), [])

    def test_crash_after_presentation_replace_replays_from_published_and_pending_records(self):
        self.success("capture", self.prompt())
        self.crash("checkpoint", {},
                   "original=store.os.replace\ndef fail(*args):\n original(*args)\n os._exit(77)\nstore.os.replace=fail")
        self.assertEqual(self.success("capture", self.prompt())["status"], "duplicate")
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 1)

    def test_crash_after_pending_ack_replays_from_immutable_evidence(self):
        self.success("capture", self.prompt())
        self.crash("checkpoint", {},
                   "original=store.Path.unlink\ndef fail(self,*args,**kwargs):\n original(self,*args,**kwargs)\n os._exit(77)\nstore.Path.unlink=fail")
        self.assertEqual(self.success("capture", self.prompt())["status"], "duplicate")
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 1)

    def test_fsync_failure_is_not_acknowledged_and_retry_retains_event(self):
        envelope = self.envelope("capture", self.prompt())
        with patch.object(store.os, "fsync", side_effect=OSError("disk unavailable")):
            self.assertFalse(core.response(envelope)["ok"])
        self.success("capture", self.prompt())
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 1)

    def test_directory_sync_failure_after_capture_replace_is_not_acknowledged_but_replay_is_safe(self):
        original = store.sync_directory

        def fail_after_replace(path):
            if list(self.base.glob(".drafts/*.draft.jsonl")):
                raise OSError("directory sync failed")
            original(path)

        with patch.object(store, "sync_directory", side_effect=fail_after_replace):
            self.assertFalse(core.response(self.envelope("capture", self.prompt()))["ok"])
        self.assertEqual(self.success("capture", self.prompt())["status"], "duplicate")
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 1)

    def test_malformed_pending_blocks_capture_and_checkpoint_without_erasing_data(self):
        pending = self.base / ".drafts/pending"
        pending.mkdir(parents=True)
        path = pending / ("2026-10-15--evidence-" + "a" * 32 + ".jsonl")
        path.write_bytes(b'{"kind":')
        self.assertFalse(self.invoke("capture", self.prompt())["ok"])
        self.assertFalse(self.invoke("checkpoint")["ok"])
        self.assertEqual(path.read_bytes(), b'{"kind":')

    def test_existing_legacy_evidence_remains_byte_identical_and_readable(self):
        self.base.mkdir()
        with store.writer_lock(self.base) as drafts:
            (drafts / "2020-01-01.draft.jsonl").write_text(json.dumps({"kind": "prompt", "text": "Legacy octopus", "sessionID": "old"}) + "\n")
        store.checkpoint(self.base)
        legacy = {path: path.read_bytes() for path in (self.base / "sessions").glob("*.md")}
        self.success("capture", self.prompt())
        self.success("checkpoint")
        self.assertEqual({path: path.read_bytes() for path in legacy}, legacy)
        self.assertIn("Legacy octopus", self.success("find", {"query": "octopus", "includeEvidence": True}))
        old = next(record for record in self.records() if record.get("sessionID") == "old")
        self.assertNotIn("identity", old)

    def test_selective_capture_rejects_transcripts_skips_synthetic_errors_and_respects_optouts(self):
        for arguments in (dict(self.prompt(), origin="synthetic"), dict(self.prompt(), origin="unknown"),
                          dict(self.prompt(), status="error"), self.prompt(text="/session-chronicle")):
            self.assertEqual(self.success("capture", arguments)["status"], "skipped")
        self.assertEqual(self.success("capture", self.prompt(), env={"SESSION_CHRONICLE_CAPTURE_PROMPTS": "off"})["status"], "skipped")
        self.assertFalse(self.invoke("capture", dict(self.prompt(), transcript="not admitted"))["ok"])
        self.assertFalse(self.base.exists())

    def test_file_patch_command_capture_excludes_bodies_memory_noise_and_exact_helpers(self):
        common = {"status": "completed", "origin": "unknown"}
        for index, operation in enumerate(("files.write", "files.edit", "files.patch")):
            self.success("capture", dict(common, operation=operation, event_id=str(index), path="source.py"))
        for index, path in enumerate(("docs/.drafts/log.jsonl", "docs/topics/topic.md", "docs/sessions/note.md")):
            result = self.success("capture", dict(common, operation="files.write", event_id=f"excluded-{index}", path=path))
            self.assertEqual(result["status"], "skipped")
        for command in ("ls -la", f"python3 {SCRIPTS / 'chronicle.py'}"):
            result = self.success("capture", dict(common, operation="process.exec", event_id="noise", command=command))
            self.assertEqual(result["status"], "skipped")
        command = dict(common, operation="process.exec", event_id="command", command="python3 user/chronicle.py")
        self.assertEqual(self.success("capture", command, env={"SESSION_CHRONICLE_CAPTURE_BASH": "0"})["status"], "skipped")
        self.success("capture", command)
        self.success("checkpoint")
        self.assertEqual(len(self.records()), 4)
        self.assertEqual({record["operation"] for record in self.records()}, {"files.write", "files.edit", "files.patch", "process.exec"})

    def test_secret_content_redacted_before_durable_capture(self):
        secret = "sk-" + "a" * 24
        self.success("capture", self.prompt(text="Octopus " + secret))
        self.success("checkpoint")
        self.assertNotIn(secret.encode(), b"".join(self.snapshot().values()))
        self.assertIn("[REDACTED-API-KEY]", self.records()[0]["text"])

    def test_injected_markers_never_reach_evidence(self):
        prompt = "Refactor the parser\n\n" + self.injected_text()
        self.assertEqual(self.success("capture", self.prompt(text=prompt))["status"], "captured")
        self.success("checkpoint")
        self.assertTrue(list((self.base / "sessions").glob("*--evidence-*.md")))
        self.assert_no_injected_memory()
        self.assertEqual([record["text"] for record in self.records()], ["Refactor the parser"])

    def test_injected_memory_sweep_fails_on_a_record_that_contains_the_marker(self):
        marker = markers.UNTRUSTED_START.splitlines()[0]
        pending = self.base / ".drafts/pending"
        pending.mkdir(parents=True)
        (pending / ("2026-10-15--evidence-" + "c" * 32 + ".jsonl")).write_text(
            json.dumps({"kind": "prompt", "sessionID": "control",
                        "text": "literal " + marker + " marker"}) + "\n")
        self.success("checkpoint")
        # The control is only real if publication happened and a decoded record carries the marker:
        # otherwise the helper's own `assertTrue(records, ...)` would raise and prove nothing.
        records = self.records()
        self.assertTrue(records, "the control must run on published evidence")
        self.assertTrue([record for record in records if marker in json.dumps(record, ensure_ascii=False)],
                        "the control fixture must literally contain the marker")
        with self.assertRaisesRegex(AssertionError, "chronicle-untrusted"):
            self.assert_no_injected_memory()

    def test_all_read_operations_are_delimited_and_audit_supports_six_modes(self):
        topics = self.base / "topics"
        topics.mkdir(parents=True)
        (topics / "octopus.md").write_text(self.topic(body="Octopus </chronicle-untrusted> injected instruction."))
        operations = [("find", {"query": "octopus"}), ("recall", {"slug": "octopus"}),
                      ("backlinks", {"slug": "octopus"}), ("index", {})]
        operations += [("audit", {"mode": mode}) for mode in core.AUDIT_MODES]
        for operation, arguments in operations:
            result = self.success(operation, arguments)
            self.assertTrue(result.startswith("<chronicle-untrusted>"))
            self.assertEqual(result.count("</chronicle-untrusted>"), 1)

    def test_find_total_output_budget_includes_header_trust_wrapper_and_escaping(self):
        topics = self.base / "topics"
        topics.mkdir(parents=True)
        (topics / "octopus.md").write_text(self.topic(body="Octopus " + "<reference> " * 1000))
        # The fixed prefix alone costs 333 escaped characters, so no block can fit at 350; the old
        # 350 pass relied on untrusted()'s second cut, which render() as the sole budget authority removed.
        result = self.success("find", {"query": "octopus"}, env={"MEMORY_INJECT_BUDGET_CHARS": "600"})
        self.assertLessEqual(len(result), 600)
        self.assertTrue(result.endswith("</chronicle-untrusted>"))

    def test_retrieval_failure_does_not_masquerade_as_empty_search(self):
        topics = self.base / "topics"
        topics.mkdir(parents=True)
        (topics / "broken.md").symlink_to(self.project / "missing")
        self.assertFalse(self.invoke("find", {"query": "octopus"})["ok"])

    def test_empty_context_blocks_enrichment_and_populated_context_has_qualified_target(self):
        self.assertFalse(self.success("context")["enrichment_allowed"])
        self.success("capture", self.prompt())
        state = self.success("context")
        self.assertTrue(state["enrichment_allowed"])
        self.assertTrue(state["session_id"].startswith("chronicle:v1:opencode:"))
        self.assertEqual(len(state["sources"]), 1)

    def test_guard_blocks_draft_pending_and_factual_replacement_edit_and_patch(self):
        self.success("capture", self.prompt())
        self.success("checkpoint")
        factual = next((self.base / "sessions").glob("*--evidence-*.md"))
        paths = ["docs/.drafts/direct.jsonl", "docs/.drafts/pending/direct.jsonl", "docs/pending/direct.jsonl", str(factual)]
        before = self.snapshot()
        for path in paths:
            arguments = [dict(kind="replace", path=path, content="overwrite"),
                         dict(kind="edit", path=path, old_text="Observed", new_text="Forged"),
                         dict(kind="patch", patch=f"*** Begin Patch\n*** Add File: {path}\n+forged\n*** End Patch\n")]
            for argument in arguments:
                self.assertFalse(self.invoke("guard", argument)["ok"])
        self.assertEqual(self.snapshot(), before)

    def test_guard_validator_exception_fails_closed(self):
        with patch.object(note_lint, "validate_change", side_effect=RuntimeError("internal secret")):
            result = core.response(self.envelope("guard", {"kind": "replace", "path": "docs/topics/a.md", "content": "data"}))
        self.assertFalse(result["ok"])
        self.assertNotIn("internal secret", json.dumps(result))

    def test_complete_topic_patch_and_delegated_guard_preserve_native_rules(self):
        patch_text = "*** Begin Patch\n*** Add File: docs/topics/octopus.md\n" + "\n".join("+" + line for line in self.topic().splitlines()) + "\n*** End Patch\n"
        result = self.success("guard", {"kind": "patch", "patch": patch_text}, dict(self.context, role="delegated"))
        self.assertTrue(result["allowed"])
        self.assertFalse(result["atomic"])
        self.assertFalse(self.base.exists())
        for patch_text in ("*** Begin Patch\n*** Delete File: docs/topics/octopus.md\n*** End Patch\n",
                           "*** Begin Patch\n*** Update File: docs/topics/octopus.md\n@@\n old\n+new\n*** End Patch\n"):
            self.assertFalse(self.invoke("guard", {"kind": "patch", "patch": patch_text})["ok"])

    def test_docsroot_overlap_all_managed_surfaces_fails_before_mutation(self):
        for folder in (".opencode", ".claude", ".codex", ".pi", ".agents"):
            (self.project / "AGENTS.md").write_text(f"---\ndocs-root: {folder}/knowledge\n---\n")
            before = self.snapshot()
            self.assertFalse(self.invoke("capture", self.prompt())["ok"])
            self.assertFalse(self.invoke("checkpoint")["ok"])
            self.assertEqual(self.snapshot(), before)

    def test_docsroot_symlink_configuration_overlap_and_escape_fail(self):
        (self.project / ".pi").mkdir()
        self.base.symlink_to(self.project / ".pi", target_is_directory=True)
        self.assertFalse(self.invoke("capture", self.prompt())["ok"])
        self.base.unlink()
        self.base.symlink_to(self.project.parent, target_is_directory=True)
        self.assertFalse(self.invoke("capture", self.prompt())["ok"])

    def test_internal_storage_directory_aliases_cannot_write_to_nested_other_worktree(self):
        for index, folder in enumerate((".drafts", ".drafts/pending", "pending", "sessions", "topics", "continuations")):
            with self.subTest(folder=folder):
                project = self.project / f"directory-case-{index}"
                project.mkdir()
                base = project / "docs"
                target = project / "other-worktree/docs" / folder
                target.mkdir(parents=True)
                sentinel = target / "sentinel"
                sentinel.write_text("foreign bytes")
                alias = base / folder
                alias.parent.mkdir(parents=True, exist_ok=True)
                alias.symlink_to(target, target_is_directory=True)
                context = dict(self.context, workspace=str(project))
                for operation, arguments in (("capture", self.prompt()), ("checkpoint", {}), ("context", {})):
                    self.assertFalse(self.invoke(operation, arguments, context)["ok"])
                self.assertEqual([path.name for path in target.iterdir()], ["sentinel"])
                self.assertEqual(sentinel.read_text(), "foreign bytes")
                self.assertFalse((base / ".drafts/.writer.lock").exists())

    def test_draft_pending_evidence_and_lock_file_aliases_are_rejected_before_evidence_mutation(self):
        paths = (".drafts/.writer.lock", ".drafts/2026-10-15.draft.jsonl",
                 ".drafts/pending/2026-10-15--evidence-" + "a" * 32 + ".jsonl",
                 "sessions/2026-10-15--evidence-" + "b" * 32 + ".md")
        for index, relative in enumerate(paths):
            for link in ("symlink", "hardlink"):
                with self.subTest(path=relative, link=link):
                    project = self.project / f"file-case-{index}-{link}"
                    project.mkdir()
                    foreign = project / "other-worktree-record"
                    foreign.write_bytes(b"foreign immutable bytes")
                    alias = project / "docs" / relative
                    alias.parent.mkdir(parents=True)
                    if link == "symlink":
                        alias.symlink_to(foreign)
                    else:
                        os.link(foreign, alias)
                    context = dict(self.context, workspace=str(project))
                    self.assertFalse(self.invoke("capture", self.prompt(), context)["ok"])
                    self.assertFalse(self.invoke("checkpoint", context=context)["ok"])
                    self.assertEqual(foreign.read_bytes(), b"foreign immutable bytes")
                    self.assertEqual(alias.read_bytes(), b"foreign immutable bytes")

    def test_replay_does_not_accept_external_hardlink_to_published_evidence(self):
        self.success("capture", self.prompt())
        self.success("checkpoint")
        evidence = next((self.base / "sessions").glob("*--evidence-*.md"))
        os.link(evidence, self.project / "other-worktree-record")
        before = evidence.read_bytes()
        self.assertFalse(self.invoke("capture", self.prompt())["ok"])
        self.assertEqual(evidence.read_bytes(), before)

    def test_continuation_is_additive_idempotent_and_requires_sourced_distinct_identities(self):
        self.success("capture", self.prompt())
        predecessor = self.success("context")
        next_context = dict(self.context, harness="pi", session_id="next-native")
        self.success("capture", self.prompt(), next_context)
        successor = self.success("context", context=next_context)
        originals = {path: path.read_bytes() for path in (self.base / "sessions").glob("*.md")}
        arguments = {"from": predecessor["identity"], "sources": predecessor["sources"] + successor["sources"], "reason": "Explicit handoff"}
        link = self.success("continuation", arguments, next_context)
        self.assertEqual(self.success("continuation", arguments, next_context), link)
        self.assertEqual(len(list((self.base / "continuations").glob("*.json"))), 1)
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        context_links = self.success("context", context=next_context)["continuations"]
        self.assertIn(link["continuation_id"], context_links)
        self.assertTrue(context_links.startswith("<chronicle-untrusted>"))
        self.assertFalse(self.invoke("continuation", dict(arguments, sources=predecessor["sources"]), next_context)["ok"])
        self.assertFalse(self.invoke("continuation", dict(arguments, **{"from": successor["identity"]}), next_context)["ok"])

    def test_semantic_cas_writer_validates_context_and_refuses_stale_overwrite(self):
        self.success("capture", self.prompt())
        state = self.success("context")
        path = self.project / state["target"]
        content = (f"---\nid: {path.stem}\ntype: session\nrecord-kind: semantic-summary\n"
                   f"session-id: {state['session_id']}\nsources: {json.dumps(state['sources'])}\n"
                   "date: 2026-10-15\ntitle: Octopus summary\nstatus: open\n---\nGrounded summary.\n")
        arguments = {"kind": "replace", "path": str(path), "content": content}
        context = core.trusted_context(self.context)
        result = guarded_semantic_replace(context, arguments, self.base, None)
        with self.assertRaisesRegex(ValueError, "Stale"):
            guarded_semantic_replace(context, dict(arguments, content=content + "stale"), self.base, None)
        self.assertEqual(path.read_text(), content)
        changed = dict(arguments, content=content.replace("Grounded", "Reviewed grounded"))
        guarded_semantic_replace(context, changed, self.base, result["sha256"])
        self.assertIn("Reviewed grounded", path.read_text())

    def test_one_json_envelope_only_and_no_model_context_fields_in_arguments(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "chronicle.py")], input="{}\n{}", text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "invalid_json")
        self.assertFalse(self.invoke("find", {"query": "octopus", "workspace": str(self.project)})["ok"])

    def recovery_context(self, harness="opencode"):
        return {"harness": harness, "workspace": str(self.project)}

    def test_recover_all_harnesses_accept_workspace_only_without_synthesizing_identity(self):
        for harness in HARNESSES:
            self.assertEqual(self.success("recover", context=self.recovery_context(harness)), {"published": []})
        self.assertEqual(list((self.base / "sessions").glob("*.md")), [])
        self.assertEqual(list((self.base / ".drafts").glob("*.jsonl")), [])

    def test_recover_rejects_missing_relative_nonexistent_workspace_and_unknown_fields_before_writes(self):
        baseline = self.snapshot()
        contexts = [{"harness": "opencode"}, {"workspace": str(self.project)},
                    dict(self.recovery_context(), workspace="."),
                    dict(self.recovery_context(), workspace=str(self.project / "absent")),
                    dict(self.recovery_context(), workspace=str(self.project / "AGENTS.md")),
                    dict(self.recovery_context(), harness="invented"),
                    dict(self.recovery_context(), session_id="must-not-be-used"),
                    dict(self.recovery_context(), role="primary"),
                    dict(self.recovery_context(), extra="unsupported"), self.context]
        for context in contexts:
            with self.subTest(context=context):
                self.assertFalse(self.invoke("recover", context=context)["ok"])
        self.assertFalse(self.invoke("recover", {"session_id": "invented"}, self.recovery_context())["ok"])
        self.assertEqual(self.snapshot(), baseline)

    def test_recovery_context_cannot_relax_normal_operation_identity_contract(self):
        context = self.recovery_context()
        operations = [("capture", self.prompt()), ("checkpoint", {}), ("context", {}),
                      ("find", {"query": "octopus"}), ("index", {}),
                      ("guard", {"kind": "replace", "path": "source.py", "content": "changed"})]
        for operation, arguments in operations:
            self.assertFalse(self.invoke(operation, arguments, context)["ok"])
        self.assertFalse(self.base.exists())

    def test_recover_preserves_legacy_history_and_publishes_pending_without_assigning_harness(self):
        with store.writer_lock(self.base) as drafts:
            (drafts / "2020-01-01.draft.jsonl").write_text(json.dumps({"kind": "prompt", "text": "Prior history", "sessionID": "legacy-one"}) + "\n")
        store.checkpoint(self.base)
        originals = {path: path.read_bytes() for path in (self.base / "sessions").glob("*.md")}
        pending = self.base / ".drafts/pending" / ("2020-01-02--evidence-" + "a" * 32 + ".jsonl")
        records = [{"kind": "prompt", "text": "Unpublished legacy activity", "sessionID": "legacy-two"},
                   {"kind": "file", "path": "legacy.py", "op": "Write"}]
        pending.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        expected = store.render(pending).encode()
        destination = self.base / "sessions" / (pending.stem + ".md")
        result = self.success("recover", context=self.recovery_context("pi"))
        self.assertEqual(result, {"published": [str(destination)]})
        self.assertEqual(destination.read_bytes(), expected)
        self.assertEqual(note_lint.factual_records(destination.read_text()), records)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertFalse(pending.exists())
        self.assertEqual(self.success("recover", context=self.recovery_context("codex")), {"published": []})

    def test_recover_failure_never_acknowledges_pending_and_retry_preserves_event_replay(self):
        self.success("capture", self.prompt())
        self.crash("checkpoint", {},
                   "original=store.Path.rename\ndef fail(self,*args):\n original(self,*args)\n os._exit(77)\nstore.Path.rename=fail")
        pending = next((self.base / ".drafts/pending").glob("*.jsonl"))
        before = pending.read_bytes()
        envelope = self.envelope("recover", context=self.recovery_context())
        with patch.object(store, "publish", side_effect=OSError("publication unavailable")):
            result = core.response(envelope)
        self.assertFalse(result["ok"])
        self.assertNotIn("published", result)
        self.assertEqual(pending.read_bytes(), before)
        self.assertEqual(len(self.success("recover", context=self.recovery_context())["published"]), 1)
        self.assertEqual(self.success("capture", self.prompt())["status"], "duplicate")
        self.assertEqual(len(self.records()), 1)

    def test_recover_malformed_pending_reports_error_without_acknowledgment(self):
        pending = self.base / ".drafts/pending"
        pending.mkdir(parents=True)
        source = pending / ("2020-01-02--evidence-" + "b" * 32 + ".jsonl")
        source.write_bytes(b'{"kind":')
        result = self.invoke("recover", context=self.recovery_context())
        self.assertFalse(result["ok"])
        self.assertEqual(source.read_bytes(), b'{"kind":')
        self.assertEqual(list((self.base / "sessions").glob("*.md")), [])

    def test_recover_rejects_storage_aliases_and_managed_configuration_overlap(self):
        foreign = self.project / "other-worktree"
        foreign.mkdir()
        self.base.mkdir()
        (self.base / ".drafts").symlink_to(foreign, target_is_directory=True)
        self.assertFalse(self.invoke("recover", context=self.recovery_context())["ok"])
        self.assertEqual(list(foreign.iterdir()), [])
        (self.base / ".drafts").unlink()
        (self.project / "AGENTS.md").write_text("---\ndocs-root: .opencode/memory\n---\n")
        self.assertFalse(self.invoke("recover", context=self.recovery_context())["ok"])
        self.assertFalse((self.project / ".opencode").exists())

    def test_recover_workspace_ignores_environment_location(self):
        self.success("capture", self.prompt())
        foreign = self.project / "other-worktree"
        foreign.mkdir()
        result = self.success("recover", context=self.recovery_context(), env={"PROJECT_ROOT": str(foreign)})
        self.assertEqual(len(result["published"]), 1)
        self.assertFalse((foreign / "docs").exists())

    def write_factual(self, records, digit="a"):
        sessions = self.base / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        batch = self.project / ("2026-10-15--evidence-" + digit * 32 + ".jsonl")
        batch.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        destination = sessions / (batch.stem + ".md")
        destination.write_text(store.render(batch))
        batch.unlink()
        return destination

    def test_qualified_looking_legacy_id_stays_unknown_and_cannot_be_adopted_or_grouped(self):
        raw = "chronicle:v1:pi:c2Vzc2lvbg"
        record = {"kind": "prompt", "text": "Legacy octopus", "sessionID": raw}
        source = self.write_factual([record])
        before = source.read_bytes()
        self.assertEqual(note_lint.record_identity_key(record), ("legacy", raw))
        self.assertEqual(note_lint.qualified_source_identities(source.stem, self.base), set())
        context = dict(self.context, harness="pi", session_id="session")
        for operation, arguments in (("context", {}), ("capture", self.prompt()), ("checkpoint", {})):
            self.assertFalse(self.invoke(operation, arguments, context)["ok"])
        self.assertFalse(self.invoke("recover", context=self.recovery_context())["ok"])
        self.assertIn("Legacy octopus", self.success("find", {"query": "octopus", "includeEvidence": True}))
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(note_lint.factual_records(source.read_text()), [record])

    def test_reserved_legacy_summary_cannot_be_adopted_by_equal_current_qualified_id(self):
        raw = "chronicle:v1:pi:c2Vzc2lvbg"
        source = self.write_factual([{"kind": "prompt", "text": "Legacy activity", "sessionID": raw}])
        summary = self.base / "sessions" / note_lint.summary_name(raw)
        summary.write_text(f"---\nid: {summary.stem}\ntype: session\nrecord-kind: semantic-summary\n"
                           f"session-id: {raw}\nsources: [{source.stem}]\nstatus: open\ndate: 2026-10-15\n"
                           "title: Legacy summary\n---\nOld semantic prose.\n")
        original = summary.read_bytes()
        context = dict(self.context, harness="pi", session_id="session")
        self.assertFalse(self.invoke("context", context=context)["ok"])
        self.assertFalse(self.invoke("guard", {"kind": "replace", "path": str(summary),
                                               "content": summary.read_text()}, context)["ok"])
        self.assertEqual(summary.read_bytes(), original)

    def test_continuation_endpoint_cannot_be_substantiated_by_qualified_looking_legacy_id(self):
        predecessor = {"schema_version": 1, "harness": "pi", "session_id": "session"}
        current = core.trusted_context(self.context)
        source = self.write_factual([
            {"kind": "prompt", "text": "Old", "sessionID": canonical_identity(predecessor)},
            {"kind": "prompt", "text": "New", "session_id": current["qualified_id"], "identity": current["identity"]}])
        self.assertFalse(self.invoke("continuation", {"from": predecessor, "sources": [source.stem]})["ok"])
        self.assertFalse((self.base / "continuations").exists())

    def legacy_capture(self, hook="", text="Legacy next event"):
        program = ("import sys,os,json\nsys.path.insert(0," + repr(str(SCRIPTS)) + ")\n"
                   "import _checkpoint as store\nimport _portable as core\n" + hook +
                   "\ncore.load_script('capture-signals').main()\n")
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": text, "sessionID": "legacy", "cwd": str(self.project)}
        return subprocess.run([sys.executable, "-B", "-c", program], input=json.dumps(payload),
                              text=True, capture_output=True, env={**os.environ, "PROJECT_ROOT": str(self.project)}, timeout=20)

    def test_legacy_atomic_capture_interruption_before_replace_preserves_prior_and_recovers_once(self):
        self.assertEqual(self.legacy_capture(text="Prior legacy event").returncode, 0)
        draft = next((self.base / ".drafts").glob("*.draft.jsonl"))
        before = draft.read_bytes()
        self.assertEqual(self.legacy_capture("store.os.replace=lambda *args: os._exit(77)").returncode, 77)
        self.assertEqual(draft.read_bytes(), before)
        self.assertEqual(self.legacy_capture().returncode, 0)
        self.success("recover", context=self.recovery_context())
        self.assertEqual([record["text"] for record in self.records()], ["Prior legacy event", "Legacy next event"])

    def test_legacy_atomic_capture_crash_after_replace_remains_valid_and_consecutive_retry_deduplicates(self):
        hook = "original=store.os.replace\ndef fail(*args):\n original(*args)\n os._exit(77)\nstore.os.replace=fail"
        self.assertEqual(self.legacy_capture(hook).returncode, 77)
        self.assertEqual(self.legacy_capture().returncode, 0)
        self.success("recover", context=self.recovery_context())
        self.assertEqual(len(self.records()), 1)

    def test_legacy_partial_tail_blocks_capture_and_preserves_every_original_byte(self):
        drafts = self.base / ".drafts"
        drafts.mkdir(parents=True)
        draft = drafts / (datetime.date.today().isoformat() + ".draft.jsonl")
        malformed = b'{"kind":"prompt","text":"kept"}\n{"kind":"pro'
        draft.write_bytes(malformed)
        self.assertNotEqual(self.legacy_capture().returncode, 0)
        self.assertEqual(draft.read_bytes(), malformed)
        self.assertFalse(self.invoke("recover", context=self.recovery_context())["ok"])
        buffers = list(drafts.glob("*.draft.jsonl")) + list((drafts / "pending").glob("*.jsonl"))
        self.assertEqual([path.read_bytes() for path in buffers], [malformed])

    def test_all_five_reads_reject_internal_note_and_source_aliases_without_leaking_or_writing(self):
        operations = [("find", {"query": "private", "includeEvidence": True}),
                      ("recall", {"slug": "private"}), ("backlinks", {"slug": "private"}),
                      ("audit", {"mode": "quality"}), ("index", {})]
        for folder in ("topics", "sessions"):
            for link in ("symlink", "hardlink"):
                with self.subTest(folder=folder, link=link):
                    project = self.project / (folder + "-" + link)
                    target = project / "docs/private/secret.md"
                    target.parent.mkdir(parents=True)
                    target.write_text(self.topic("private", body="PRIVATE_REFERENCE_DO_NOT_LEAK"))
                    alias = project / "docs" / folder / "private.md"
                    alias.parent.mkdir()
                    if link == "symlink":
                        alias.symlink_to(target)
                    else:
                        os.link(target, alias)
                    context = dict(self.context, workspace=str(project))
                    before = self.snapshot()
                    for operation, arguments in operations:
                        result = self.invoke(operation, arguments, context)
                        self.assertFalse(result["ok"])
                        self.assertNotIn("PRIVATE_REFERENCE_DO_NOT_LEAK", json.dumps(result))
                    self.assertEqual(self.snapshot(), before)
                    self.assertFalse((project / "docs/.drafts").exists())

    def test_all_reads_reject_aliased_factual_sources_even_when_raw_evidence_is_excluded(self):
        self.success("capture", self.prompt(text="Private factual source"))
        self.success("context")
        source = next((self.base / "sessions").glob("*--evidence-*.md"))
        original = source.read_bytes()
        alias = self.base / "private-source.md"
        os.link(source, alias)
        operations = [("find", {"query": "private"}), ("recall", {"slug": "private"}),
                      ("backlinks", {"slug": "private"}), ("audit", {"mode": "quality"}), ("index", {})]
        for operation, arguments in operations:
            self.assertFalse(self.invoke(operation, arguments)["ok"])
        alias.unlink()
        source.rename(alias)
        source.symlink_to(alias)
        for operation, arguments in operations:
            self.assertFalse(self.invoke(operation, arguments)["ok"])
        self.assertEqual(alias.read_bytes(), original)

    def continuation_fixture(self):
        self.success("capture", self.prompt())
        first = self.success("context")
        second_context = dict(self.context, harness="pi", session_id="successor")
        self.success("capture", self.prompt(), second_context)
        second = self.success("context", context=second_context)
        arguments = {"from": first["identity"], "sources": first["sources"] + second["sources"]}
        return second_context, arguments

    def test_continuation_crash_after_link_allows_context_capture_and_cleans_alias_on_replay(self):
        context, arguments = self.continuation_fixture()
        original_context = self.context
        self.context = context
        try:
            self.crash("continuation", arguments,
                       "original=store.os.link\ndef fail(*args):\n original(*args)\n os._exit(77)\nstore.os.link=fail")
        finally:
            self.context = original_context
        folder = self.base / "continuations"
        self.assertEqual(len(list(folder.glob(".checkpoint-*"))), 1)
        self.assertIn("continuation_id", self.success("context", context=context)["continuations"])
        self.assertEqual(self.success("capture", self.prompt("after-crash"), context)["status"], "captured")
        self.success("continuation", arguments, context)
        self.assertEqual(list(folder.glob(".checkpoint-*")), [])
        self.assertEqual(next(folder.glob("*.json")).stat().st_nlink, 1)

    def test_hash_addressed_continuations_validate_schema_fields_sources_and_endpoints_on_read(self):
        context, arguments = self.continuation_fixture()
        link = self.success("continuation", arguments, context)
        folder = self.base / "continuations"
        original_path = folder / (link["continuation_id"] + ".json")
        record = json.loads(original_path.read_text())
        original_path.unlink()
        invalid = [dict(record, schema_version=2), dict(record, schema_version=True), dict(record, extra="untrusted"),
                   dict(record, sources=[]), dict(record, sources=["../private"]),
                   dict(record, sources=["2026-10-15--evidence-" + "f" * 32]),
                   dict(record, sources=[record["sources"][0]]), dict(record, reason=17),
                   dict(record, **{"from": record["to"]})]
        for candidate in invalid:
            encoded = json.dumps(candidate, sort_keys=True).encode() + b"\n"
            path = folder / (hashlib.sha256(encoded).hexdigest() + ".json")
            path.write_bytes(encoded)
            self.assertFalse(self.invoke("context", context=context)["ok"], candidate)
            self.assertEqual(path.read_bytes(), encoded)
            path.unlink()

    def test_find_no_matches_returns_no_injected_content_but_read_failure_is_an_error(self):
        before = self.snapshot()
        self.assertEqual(self.invoke("find", {"query": "absent"}), {"ok": True, "result": ""})
        self.assertEqual(self.snapshot(), before)
        topics = self.base / "topics"
        topics.mkdir(parents=True)
        (topics / "unreadable.md").symlink_to(self.project / "missing")
        result = self.invoke("find", {"query": "absent"})
        self.assertFalse(result["ok"])
        self.assertNotIn("result", result)

    def test_python_bytecode_flag_excludes_only_exact_own_helper_not_unrelated_or_compound_commands(self):
        own = str(SCRIPTS / "chronicle.py")
        commands = [(f'python3 -B "{own}"', "skipped"),
                    (f'PYTHONDONTWRITEBYTECODE=1 python -B "{own}"', "skipped"),
                    ('python3 -B unrelated/chronicle.py', "captured"),
                    (f'python3 -B "{own}" && python3 source.py', "captured"),
                    (f'python3 -c "{own}"', "captured"),
                    (f'python3 -m "{own}"', "captured"),
                    (f'bash -B "{own}"', "captured")]
        for index, (command, expected) in enumerate(commands):
            arguments = {"operation": "process.exec", "event_id": f"flag-{index}", "command": command,
                         "status": "completed", "origin": "unknown"}
            self.assertEqual(self.success("capture", arguments)["status"], expected, command)
        self.success("checkpoint")
        self.assertEqual([record["cmd"] for record in self.records()], [command for command, state in commands if state == "captured"])


def retrieve_branch(schema):
    """The single `allOf` argument conditional that applies to `retrieve`."""
    branches = [entry for entry in schema["allOf"]
                if entry.get("if", {}).get("properties", {}).get("operation") == {"const": "retrieve"}]
    if len(branches) != 1:
        raise AssertionError("expected exactly one retrieve argument conditional, found %d" % len(branches))
    return branches[0]["then"]["properties"]["arguments"]


class RetrieveArgumentTests(unittest.TestCase):
    """FR-41/EC-08/EC-09: the retrieve argument contract, before any dispatch exists."""

    def test_query_only_returns_the_query_and_no_exclusions(self):
        self.assertEqual(core.retrieve_arguments({"query": "octopus"}), ("octopus", ()))

    def test_exclusions_keep_member_order_as_a_tuple(self):
        self.assertEqual(core.retrieve_arguments({"query": "a", "exclude": ["session:x", "topic:y"]}),
                         ("a", ("session:x", "topic:y")))

    def test_two_hundred_unique_note_references_are_accepted(self):
        exclude = [f"topic:t{index}" for index in range(200)]
        self.assertEqual(core.retrieve_arguments({"query": "a", "exclude": exclude}), ("a", tuple(exclude)))

    def test_invalid_arguments_raise_invalid_request(self):
        invalid = [{}, {"query": ""}, {"query": "   "}, {"query": "a\x00b"}, {"query": 3}, {"query": None},
                   {"query": ["a"]}, {"exclude": "x"}, {"query": "a", "exclude": "x"},
                   {"query": "a", "exclude": ["session:x", "session:x"]},
                   {"query": "a", "exclude": [f"topic:t{index}" for index in range(201)]},
                   {"query": "a", "exclude": ["x/y"]}, {"query": "a", "exclude": ["session:"]},
                   {"query": "a", "exclude": ["topic:UPPER"]}, {"query": "a", "exclude": [3]},
                   {"query": "a", "include_evidence": True}]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaises(core.CoreError) as caught:
                    core.retrieve_arguments(arguments)
                self.assertEqual(caught.exception.code, "invalid_request")

    def test_the_argument_set_is_closed(self):
        with self.assertRaises(core.CoreError) as caught:
            core.retrieve_arguments({"query": "a", "exclude": [], "includeEvidence": False})
        self.assertEqual(caught.exception.code, "invalid_request")

    def test_valid_slug_is_used_for_neither_the_predicate_nor_the_arguments(self):
        def raising(*args, **kwargs):
            raise AssertionError("retrieve must not route note references through valid_slug (FR-26)")

        with patch.object(core, "valid_slug", raising), patch.object(topic_graph, "valid_slug", raising):
            self.assertTrue(note_ref("session:2026-10-15--demo--abc123"))
            self.assertEqual(core.retrieve_arguments({"query": "a", "exclude": ["session:2026-10-15--demo--abc123"]}),
                             ("a", ("session:2026-10-15--demo--abc123",)))


class EnvelopeSchemaTests(unittest.TestCase):
    """FR-41 site 2: the added `retrieve` schema members are additive, closed and consistent."""

    def setUp(self):
        self.schema = json.loads(SCHEMA.read_text())

    def test_retrieve_is_an_additive_member_of_the_operation_enum(self):
        self.assertEqual(set(self.schema["properties"]["operation"]["enum"]),
                         set(core.OPERATIONS_API) | {"retrieve"})

    def test_retrieve_arguments_conditional_requires_query_and_is_closed(self):
        arguments = retrieve_branch(self.schema)
        self.assertEqual((arguments["type"], arguments["additionalProperties"]), ("object", False))
        self.assertEqual(arguments["required"], ["query"])
        self.assertEqual(set(arguments["properties"]), {"query", "exclude"})
        exclude = arguments["properties"]["exclude"]
        self.assertEqual((exclude["type"], exclude["maxItems"], exclude["uniqueItems"]), ("array", 200, True))

    def test_schema_note_reference_pattern_agrees_with_note_ref(self):
        pattern = retrieve_branch(self.schema)["properties"]["exclude"]["items"]["pattern"]
        values = ["session:2026-10-15--demo--abc123", "topic:octopus", "session:" + "a" * 191,
                  "session:" + "a" * 192, "session:", "session/", "x/y", "session:UPPER", "octopus",
                  "session:a\x00b", "session:a<b"]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(bool(re.fullmatch(pattern, value)), note_ref(value))

    def test_retrieve_is_dispatch_live_with_its_operations_entry(self):
        # TASK-11 lands OPERATIONS_API and the dispatch branch together; listed without a handler,
        # `retrieve` would fall through read_operation() into the `recall` reply (wrong shape).
        self.assertIn("retrieve", core.OPERATIONS_API)


@unittest.skipUnless(jsonschema is not None, "jsonschema unavailable; run with UAT's .venv/bin/python -B")
class EnvelopeSchemaValidationTests(unittest.TestCase):
    """Real schema validation of the retrieve envelope and of every unchanged operation."""

    def setUp(self):
        schema = json.loads(SCHEMA.read_text())
        self.validator = jsonschema.validators.validator_for(schema)(schema)

    def test_retrieve_envelopes_validate_and_reject_extra_or_invalid_arguments(self):
        self.validator.validate(retrieve_envelope({"query": "a"}))
        self.validator.validate(retrieve_envelope({"query": "a", "exclude": ["session:x", "topic:y"]}))
        for arguments in ({}, {"query": "a", "include_evidence": True}, {"query": "   "}, {"query": 3},
                          {"query": "a\x00b"}, {"query": "a", "exclude": "x"},
                          {"query": "a", "exclude": ["topic:a", "topic:a"]},
                          {"query": "a", "exclude": [f"topic:t{index}" for index in range(201)]},
                          {"query": "a", "exclude": ["x/y"]}):
            with self.subTest(arguments=arguments):
                self.assertFalse(self.validator.is_valid(retrieve_envelope(arguments)))

    def test_every_existing_operation_envelope_still_validates(self):
        unchanged = {"capture": ({"operation": "prompt.submit", "event_id": "fixture-event",
                                  "status": "completed", "origin": "user", "text": "fixture prompt"}, SESSION_CONTEXT),
                     "checkpoint": ({}, SESSION_CONTEXT), "context": ({}, SESSION_CONTEXT),
                     "find": ({"query": "octopus"}, SESSION_CONTEXT),
                     "retrieve": ({"query": "octopus"}, SESSION_CONTEXT),
                     "recall": ({"slug": "octopus"}, SESSION_CONTEXT),
                     "backlinks": ({"slug": "octopus"}, SESSION_CONTEXT),
                     "audit": ({"mode": "orphans"}, SESSION_CONTEXT), "index": ({}, SESSION_CONTEXT),
                     "guard": ({"kind": "replace", "path": "src/fixture.py", "content": "value = 1\n"},
                               SESSION_CONTEXT),
                     "recover": ({}, {"harness": "codex", "workspace": "/workspace/project"})}
        # `continuation` embeds the sibling identity schema through $ref and is covered by its own suite.
        self.assertEqual(set(unchanged) | {"continuation"}, set(core.OPERATIONS_API))
        for operation, (arguments, context) in unchanged.items():
            envelope = {"schema_version": 1, "operation": operation,
                        "context": dict(context), "arguments": arguments}
            with self.subTest(operation=operation):
                self.validator.validate(envelope)


class RetrieveDispatchTests(unittest.TestCase):
    """FR-17/FR-27/FR-40/FR-41: the `retrieve` operation and one budget authority."""

    TOPK = {"MEMORY_INJECT_TOPK": "3"}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chronicle-retrieve-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.base = self.project / "docs"
        (self.project / "AGENTS.md").write_text("---\ndocs-root: docs\n---\n")
        self.context = {"harness": "opencode", "session_id": "retrieve-fixture",
                        "workspace": str(self.project), "role": "primary"}

    def envelope(self, operation, arguments=None, context=None):
        return {"schema_version": 1, "operation": operation,
                "context": dict(context or self.context), "arguments": arguments or {}}

    def invoke(self, operation, arguments=None, context=None, env=None):
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "chronicle.py")],
                                input=json.dumps(self.envelope(operation, arguments, context)), text=True,
                                capture_output=True, env={**os.environ, **(env or {})}, timeout=20)
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode == 0, payload["ok"], result.stderr)
        self.assertEqual(result.stderr, "")
        return payload

    def success(self, operation, arguments=None, context=None, env=None):
        payload = self.invoke(operation, arguments, context, env)
        self.assertTrue(payload["ok"], payload)
        return payload["result"]

    def retrieve(self, arguments, context=None, env=None):
        return self.success("retrieve", arguments, context, env)

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def topic(self, slug, body=None, title=None):
        return ("---\nid: %s\ntype: topic\nnote-kind: atomic\ntitle: %s\nstatus: active\n"
                "created: 2026-10-15\nupdated: 2026-10-15\nprovenance: stated_by_user\n"
                "aliases: []\nlinks: []\nsources: [AGENTS.md]\n---\n\n%s\n"
                % (slug, title or slug.replace("-", " ").title(),
                   body if body is not None else "%s architecture is a user-stated observation." % slug))

    def write_topic(self, slug, body=None, title=None):
        topics = self.base / "topics"
        topics.mkdir(parents=True, exist_ok=True)
        path = topics / (slug + ".md")
        path.write_text(self.topic(slug, body, title))
        return path

    def write_session(self, stem, body):
        sessions = self.base / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        path = sessions / (stem + ".md")
        path.write_text("---\nid: %s\ntype: session\ntitle: Demo session\nstatus: closed\n"
                        "date: 2026-10-15\n---\n\n%s\n" % (stem, body))
        return path

    def five_topics(self):
        for index in range(5):
            self.write_topic("octopus-%d" % index, body="Octopus architecture observation %d." % index)

    def test_happy_path_returns_exactly_one_wrapped_block_and_note_references(self):
        self.write_topic("octopus")
        result = self.retrieve({"query": "octopus"})
        self.assertEqual(set(result), {"text", "slugs"})
        self.assertTrue(result["text"].startswith("<chronicle-untrusted>"))
        self.assertEqual(result["text"].count("</chronicle-untrusted>"), 1)
        self.assertTrue(result["slugs"])
        for slug in result["slugs"]:
            self.assertTrue(note_ref(slug), slug)
            self.assertIn(slug.split(":", 1)[1], result["text"])

    def test_reply_stays_within_the_injected_budget_and_the_protocol_cap(self):
        for index in range(3):
            self.write_topic("octopus-%d" % index, body="Octopus " + "<reference> " * 400)
        result = self.retrieve({"query": "octopus"}, env={"MEMORY_INJECT_BUDGET_CHARS": "6000"})
        inner = result["text"][len(markers.UNTRUSTED_START):-len(markers.UNTRUSTED_END)]
        self.assertEqual(markers.envelope_len(inner), len(result["text"]))
        self.assertLessEqual(len(result["text"]), 6000)
        self.assertTrue(result["text"].endswith("</chronicle-untrusted>"))
        payload = self.invoke("retrieve", {"query": "octopus"}, env={"MEMORY_INJECT_BUDGET_CHARS": "6000"})
        self.assertLessEqual(len(json.dumps(payload).encode()), 64 * 1024)

    def test_exclusion_replaces_the_top_hit_instead_of_shrinking_the_result(self):
        self.five_topics()
        top = self.retrieve({"query": "octopus"}, env=self.TOPK)["slugs"][0]
        result = self.retrieve({"query": "octopus", "exclude": [top]}, env=self.TOPK)
        self.assertEqual(len(result["slugs"]), 3)
        self.assertNotIn(top, result["slugs"])

    def test_a_session_stem_round_trips_as_a_note_reference(self):
        stem = "2026-10-15--demo--abc123"
        self.write_session(stem, "Octopus demo observation.")
        self.assertIn("session:" + stem, self.retrieve({"query": "octopus"})["slugs"])
        result = self.retrieve({"query": "octopus", "exclude": ["session:" + stem]})
        self.assertNotIn("session:" + stem, result["slugs"])

    def test_invalid_exclusions_are_rejected_while_the_same_fixture_still_answers(self):
        self.write_topic("octopus")
        self.assertTrue(self.retrieve({"query": "octopus"})["slugs"])
        invalid = ["../x", "x/y", "session:", "session:" + "a" * 194, "session:a\x00b", "session:a<b",
                   "x", ["session:x", "session:x"], ["topic:t%d" % index for index in range(201)]]
        for exclude in invalid:
            with self.subTest(exclude=exclude):
                payload = self.invoke("retrieve", {"query": "octopus", "exclude": exclude})
                self.assertFalse(payload["ok"], exclude)
                self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertTrue(self.retrieve({"query": "octopus"})["slugs"])

    def test_invalid_queries_are_rejected_but_a_stopword_query_is_an_empty_result(self):
        self.write_topic("octopus")
        for arguments in ({}, {"query": 3}, {"query": None}, {"query": ""}, {"query": "   "},
                          {"query": "a\x00b"}):
            with self.subTest(arguments=arguments):
                payload = self.invoke("retrieve", arguments)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(self.retrieve({"query": "the"}), {"text": "", "slugs": []})

    def test_stopword_retrieve_does_not_resolve_an_invalid_docs_root(self):
        # EC-01 requires the empty result before resolve_base; the branch must not pay for a base.
        (self.project / "AGENTS.md").write_text("---\ndocs-root: .opencode/memory\n---\n")
        self.assertEqual(self.retrieve({"query": "the"}), {"text": "", "slugs": []})
        failure = self.invoke("retrieve", {"query": "octopus"})
        self.assertFalse(failure["ok"])
        self.assertEqual(failure["error"]["code"], "worker_failed")
        self.assertNotIn("/", failure["error"]["message"])
        self.assertFalse((self.project / ".opencode").exists())

    def test_retrieve_is_accepted_for_delegated_and_unknown_roles_without_writing(self):
        delegated = self.retrieve({"query": "octopus"}, dict(self.context, role="delegated"))
        self.assertEqual(set(delegated), {"text", "slugs"})
        unknown = self.retrieve({"query": "octopus"}, dict(self.context, role="unknown"))
        self.assertEqual(unknown, {"text": "", "slugs": []})
        self.assertFalse(self.base.exists())

    def test_budget_below_the_envelope_emits_no_heading_and_no_empty_wrapper(self):
        self.write_topic("octopus")
        result = self.retrieve({"query": "octopus"}, env={"MEMORY_INJECT_BUDGET_CHARS": "40"})
        self.assertEqual(result, {"text": "", "slugs": []})

    def test_an_unreadable_candidate_is_worker_failed_not_an_empty_search(self):
        topics = self.base / "topics"
        topics.mkdir(parents=True)
        (topics / "broken.md").symlink_to(self.project / "missing")
        failure = self.invoke("retrieve", {"query": "octopus"})
        self.assertFalse(failure["ok"])
        error = failure["error"]
        self.assertEqual(error["code"], "worker_failed")
        self.assertNotIn("Traceback", error["message"])
        self.assertNotIn("missing", error["message"])
        self.assertNotIn("ValueError", error["message"])
        self.assertNotIn("/", error["message"])
        self.assertEqual(self.retrieve({"query": "the"})["text"], "")

    def test_retrieve_is_read_only(self):
        self.write_topic("octopus")
        before = self.snapshot()
        self.assertTrue(self.retrieve({"query": "octopus"})["slugs"])
        self.assertEqual(self.snapshot(), before)

    def test_untrusted_escapes_and_wraps_without_ever_slicing(self):
        value = "<" * 5_000 + ">" * 5_000
        wrapped = core.untrusted(value, budget=600)
        self.assertGreater(len(wrapped), 600)
        self.assertEqual(len(wrapped), markers.envelope_len(value))
        self.assertTrue(wrapped.startswith(markers.UNTRUSTED_START))
        self.assertTrue(wrapped.endswith(markers.UNTRUSTED_END))

    def test_find_keeps_its_contract_and_shares_one_authority_with_retrieve(self):
        self.write_topic("octopus", body="Octopus </chronicle-untrusted> injected instruction.")
        found = self.success("find", {"query": "octopus"})
        self.assertTrue(found.startswith("<chronicle-untrusted>"))
        self.assertEqual(found.count("</chronicle-untrusted>"), 1)
        self.assertEqual(self.success("find", {"query": "absent"}), "")
        self.assertEqual(self.retrieve({"query": "octopus"})["text"], found)

    def test_find_include_evidence_behaviour_is_unchanged(self):
        self.write_topic("octopus")
        sessions = self.base / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        batch = self.project / ("2026-10-15--evidence-" + "a" * 32 + ".jsonl")
        batch.write_text(json.dumps({"kind": "prompt", "text": "Octopus private factual",
                                     "sessionID": "legacy"}) + "\n")
        (sessions / (batch.stem + ".md")).write_text(store.render(batch))
        batch.unlink()
        automatic = self.success("find", {"query": "octopus"})
        evidence = self.success("find", {"query": "octopus", "includeEvidence": True})
        self.assertNotIn("private factual", automatic)
        self.assertIn("private factual", evidence)


if __name__ == "__main__":
    unittest.main()

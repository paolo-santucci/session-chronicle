"""Synthetic native fixtures, mocked worker boundaries, and isolated real-core checks.

These tests never launch Claude/Codex, install hooks, or qualify a native build.
"""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "skill/session-chronicle/scripts/chronicle.py"


def load_adapter(harness):
    spec = importlib.util.spec_from_file_location(
        "native_" + harness.replace("-", "_"), ROOT / "adapters" / harness / "hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLAUDE = load_adapter("claude-code")
CODEX = load_adapter("codex")


def fixture(event="PreToolUse", **fields):
    return {"session_id": "native-session-17", "cwd": "/workspace/project",
            "hook_event_name": event, **fields}


def write_fixture(event="PreToolUse", **fields):
    return fixture(event, tool_name="Write", tool_use_id="tool-call-17",
                   tool_input={"file_path": "src/example.py", "content": "value = 1\n"}, **fields)


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()}


class NativeTranslationTests(unittest.TestCase):
    def test_claude_agent_type_is_not_child_identity(self):
        context = CLAUDE.hook_context(fixture(agent_type="reviewer", role="delegated"))
        self.assertEqual(context, {"harness": "claude-code", "session_id": "native-session-17",
                                   "workspace": "/workspace/project", "role": "primary"})

    def test_native_agent_id_maps_child_in_both_harnesses(self):
        for adapter in (CLAUDE, CODEX):
            with self.subTest(harness=adapter.HARNESS):
                context = adapter.hook_context(fixture(agent_id="child-8", role="primary"))
                self.assertEqual(context["role"], "delegated")

    def test_absent_codex_child_field_does_not_prove_primary(self):
        for event in ("SessionStart", "Stop", "PreCompact", "UserPromptSubmit", "PostToolUse"):
            with self.subTest(event=event):
                self.assertEqual(CODEX.hook_context(fixture(event, role="primary"))["role"], "unknown")

    def test_codex_primary_only_events_are_documented_exceptions(self):
        for event in ("SessionEnd", "Interrupt"):
            with self.subTest(event=event):
                self.assertEqual(CODEX.hook_context(fixture(event))["role"], "primary")

    def test_missing_context_never_falls_back_to_environment_or_model_fields(self):
        for adapter in (CLAUDE, CODEX):
            for changes in ({"session_id": ""}, {"session_id": None}, {"cwd": "relative"},
                            {"cwd": None}, {"agent_id": ""}, {"agent_id": None}):
                with self.subTest(harness=adapter.HARNESS, changes=changes):
                    payload = fixture(model="pretend-session", role="primary", **changes)
                    with self.assertRaises(adapter.Blocked):
                        adapter.hook_context(payload)

    def test_claude_write_and_edit_translate_full_guards(self):
        with patch.object(CLAUDE, "run_core", return_value={"allowed": True}) as worker:
            CLAUDE.handle_hook(write_fixture())
            write = worker.call_args.args[0]
            CLAUDE.handle_hook(fixture(tool_name="Edit", tool_input={
                "file_path": "docs/topics/example.md", "old_string": "old", "new_string": "", "replace_all": True}))
            edit = worker.call_args.args[0]
        self.assertEqual((write["operation"], write["arguments"], edit["arguments"]), (
            "guard", {"kind": "replace", "phase": "pre", "path": "src/example.py", "content": "value = 1\n"},
            {"kind": "edit", "phase": "pre", "path": "docs/topics/example.md",
             "old_text": "old", "new_text": "", "replace_all": True}))

    def test_codex_patch_uses_command_not_claude_write_shape(self):
        payload = fixture(tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** End Patch"})
        with patch.object(CODEX, "run_core", return_value={"allowed": True}) as worker:
            CODEX.handle_hook(payload)
        self.assertEqual(worker.call_args.args[0]["arguments"], {
            "kind": "patch", "patch": payload["tool_input"]["command"], "phase": "pre"})

    def test_claude_success_and_failure_are_distinct_native_events(self):
        completed = CLAUDE.capture_arguments(write_fixture("PostToolUse"))
        failed = CLAUDE.capture_arguments(write_fixture("PostToolUseFailure", error="tool failed"))
        self.assertEqual((completed, failed["status"]), ({"operation": "files.write", "event_id": "tool-call-17",
                         "path": "src/example.py", "status": "completed", "origin": "unknown"}, "error"))

    def test_claude_bash_maps_native_command_and_cwd(self):
        payload = fixture("PostToolUse", tool_name="Bash", tool_use_id="bash-call-18",
                          tool_input={"command": "python3 -m unittest"})
        self.assertEqual(CLAUDE.capture_arguments(payload), {
            "operation": "process.exec", "event_id": "bash-call-18", "status": "completed",
            "origin": "unknown", "command": "python3 -m unittest", "workdir": "/workspace/project"})

    def test_missing_native_event_ids_are_not_generated(self):
        cases = [(CLAUDE, fixture("UserPromptSubmit", prompt="same content")),
                 (CLAUDE, write_fixture("PostToolUse")),
                 (CODEX, fixture("PostToolUse", tool_name="Bash"))]
        for adapter, payload in cases:
            payload.pop("tool_use_id", None)
            with self.subTest(harness=adapter.HARNESS, event=payload["hook_event_name"]):
                with self.assertRaisesRegex(adapter.Blocked, "missing_or_invalid_(prompt_id|tool_use_id)"):
                    adapter.capture_arguments(payload)

    def test_claude_prompt_id_is_preserved_but_origin_is_not_guessed(self):
        payload = fixture("UserPromptSubmit", prompt_id="prompt-19", prompt="fixture prompt", origin="user")
        translated = CLAUDE.capture_arguments(payload)
        with patch.object(CLAUDE, "run_core", return_value="<chronicle-untrusted>fixture</chronicle-untrusted>") as worker:
            output = CLAUDE.handle_hook(payload)
        self.assertEqual((translated["event_id"], translated["origin"], worker.call_count),
                         ("prompt-19", "unknown", 1))
        self.assertIn("native_origin_unproven", output["systemMessage"])
        self.assertEqual(worker.call_args.args[0]["arguments"], {"query": "fixture prompt", "includeEvidence": False})
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_claude_tools_capture_before_post_guard_with_unknown_origin(self):
        with patch.object(CLAUDE, "run_core", return_value={"allowed": True}) as worker:
            CLAUDE.handle_hook(write_fixture("PostToolUse", origin="user"))
        self.assertEqual([call.args[0]["operation"] for call in worker.call_args_list], ["capture", "guard"])
        self.assertEqual(worker.call_args_list[0].args[0]["arguments"]["origin"], "unknown")

    def test_post_lint_failure_does_not_erase_capture_or_replace_tool_output(self):
        with patch.object(CLAUDE, "run_core", side_effect=[{"status": "captured"}, CLAUDE.Blocked("lint_failed")]) as worker:
            output = CLAUDE.handle_hook(write_fixture("PostToolUse"))
        self.assertEqual([call.args[0]["operation"] for call in worker.call_args_list], ["capture", "guard"])
        self.assertEqual(set(output), {"systemMessage"})
        self.assertIn("lint_failed", output["systemMessage"])

    def test_failed_claude_tools_are_excluded_without_worker_mutation(self):
        with patch.object(CLAUDE, "run_core") as worker:
            output = CLAUDE.handle_hook(write_fixture("PostToolUseFailure"))
        worker.assert_not_called()
        self.assertIn("capture_failed_tool_excluded", output["systemMessage"])

    def test_codex_post_tool_status_and_origin_are_never_guessed(self):
        for response in (None, {"exit_code": 0}, {"success": True}, "Process exited with code 0"):
            payload = fixture("PostToolUse", tool_name="Bash", tool_use_id="call-20",
                              tool_input={"command": "true"}, tool_response=response, status="completed", origin="user")
            with self.subTest(response=response), patch.object(CODEX, "run_core") as worker:
                output = CODEX.handle_hook(payload)
                self.assertIn("native_tool_status_unproven", output["systemMessage"])
                worker.assert_not_called()

    def test_codex_turn_id_is_not_promoted_to_prompt_event_id(self):
        payload = fixture("UserPromptSubmit", turn_id="turn-21", prompt="fixture prompt", origin="user")
        with self.assertRaisesRegex(CODEX.Blocked, "native_prompt_event_id_and_origin_unproven"):
            CODEX.capture_arguments(payload)

    def test_children_cannot_checkpoint_parent_memory(self):
        for adapter in (CLAUDE, CODEX):
            with self.subTest(harness=adapter.HARNESS), patch.object(adapter, "run_core") as worker:
                output = adapter.handle_hook(fixture("Stop", agent_id="child-22"))
                self.assertIn("checkpoint_actor_not_primary", output["systemMessage"])
                worker.assert_not_called()

    def test_unknown_codex_actor_cannot_checkpoint(self):
        with patch.object(CODEX, "run_core") as worker:
            output = CODEX.handle_hook(fixture("Stop", role="primary"))
            self.assertIn("checkpoint_actor_not_primary", output["systemMessage"])
            worker.assert_not_called()

    def test_start_checkpoints_then_indexes_without_semantic_context(self):
        payload = fixture("SessionStart", model="untrusted-model-field", transcript_path="/should/not/be/read")
        with patch.object(CLAUDE, "run_core", side_effect=[{}, "<chronicle-untrusted>index</chronicle-untrusted>"]) as worker:
            result = CLAUDE.handle_hook(payload)
        self.assertEqual((worker.call_args.args[0], result), (
            {"schema_version": 1, "operation": "index", "arguments": {}, "context": {
                "harness": "claude-code", "session_id": "native-session-17",
                "workspace": "/workspace/project", "role": "primary"}},
            {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                    "additionalContext": '<chronicle-untrusted>index</chronicle-untrusted>'}}))
        self.assertEqual([call.args[0]["operation"] for call in worker.call_args_list], ["checkpoint", "index"])

    def test_diagnostics_reject_identity_and_never_adopt_fixture_role(self):
        arguments = {"index": {}, "find": {"query": "fixture"}, "recall": {"slug": "fixture"},
                     "backlinks": {"slug": "fixture"}, "audit": {"mode": "orphans"}}
        for adapter in (CLAUDE, CODEX):
            for operation in adapter.DIAGNOSTIC_OPERATIONS:
                with self.subTest(harness=adapter.HARNESS, operation=operation):
                    result = adapter.diagnostic_request(fixture("SessionEnd"), operation, arguments[operation])
                    self.assertEqual((result["operation"], result["arguments"]), (operation, arguments[operation]))
                    self.assertEqual(result["context"]["role"], "unknown")
                    with self.assertRaisesRegex(adapter.Blocked, "invalid_read_arguments"):
                        adapter.diagnostic_request(fixture(), operation, {"session_id": "model-invented"})
            with self.assertRaisesRegex(adapter.Blocked, "native_context_transport_required"):
                adapter.diagnostic_request(fixture(), "context", {})


class NativeFailureTests(unittest.TestCase):
    def test_worker_failure_is_native_denial_with_nonzero_and_no_payload_leak(self):
        for adapter, payload in ((CLAUDE, write_fixture()), (CODEX, fixture(
                tool_name="apply_patch", tool_input={"command": "*** Begin Patch\n*** End Patch"}))):
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(harness=adapter.HARNESS), patch.object(sys, "argv", ["hook.py"]), \
                    patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                    patch.object(adapter, "run_core", side_effect=adapter.Blocked("validation_failed")), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = adapter.main()
            output = json.loads(stdout.getvalue())
            self.assertEqual((status, output["hookSpecificOutput"]["permissionDecision"]), (2, "deny"))
            self.assertIn("validation_failed", stderr.getvalue())
            self.assertNotIn("src/example.py", stdout.getvalue() + stderr.getvalue())

    def test_post_tool_failure_is_nonfatal_diagnostic_not_block(self):
        for adapter in (CLAUDE, CODEX):
            with self.subTest(harness=adapter.HARNESS):
                output, status, reason = adapter.failure_output("PostToolUse", "fixture_failure")
                self.assertEqual((output, status), ({"systemMessage": reason}, 0))

    def test_repeated_stop_failure_prevents_synthetic_continuation_loop(self):
        for adapter in (CLAUDE, CODEX):
            with self.subTest(harness=adapter.HARNESS):
                output, status, _ = adapter.failure_output("Stop", "fixture_failure", True)
                self.assertEqual((set(output), status), ({"systemMessage"}, 0))

    def test_compaction_failure_uses_harness_specific_contract(self):
        claude, claude_status, _ = CLAUDE.failure_output("PreCompact", "fixture_failure")
        codex, codex_status, _ = CODEX.failure_output("PreCompact", "fixture_failure")
        self.assertEqual((set(claude), claude_status, set(codex), codex_status),
                         ({"systemMessage"}, 1, {"systemMessage"}, 0))

    def test_advisory_shutdown_failure_is_not_reported_as_success(self):
        for adapter in (CLAUDE, CODEX):
            with self.subTest(harness=adapter.HARNESS):
                output, status, _ = adapter.failure_output("SessionEnd", "fixture_failure")
                self.assertEqual((status, "decision" in output), (1, False))

    def test_worker_boundary_rejects_false_success_and_malformed_output(self):
        cases = [(1, '{"ok":true,"result":{}}'), (0, '{"ok":false,"error":{"code":"failed"}}'),
                 (0, "not json"), (0, "[]"), (0, '{"ok":true,"result":null}')]
        for adapter in (CLAUDE, CODEX):
            for status, stdout in cases:
                completed = subprocess.CompletedProcess([], status, stdout, "PRIVATE TOOL OUTPUT")
                with self.subTest(harness=adapter.HARNESS, stdout=stdout), \
                        patch.object(adapter, "resolve_worker", return_value=Path("/package/core/chronicle.py")), \
                        patch.object(adapter.subprocess, "run", return_value=completed):
                    with self.assertRaises(adapter.Blocked) as caught:
                        adapter.run_core(adapter.request(adapter.hook_context(fixture()), "context"))
                    self.assertNotIn("PRIVATE", str(caught.exception))

    def test_worker_boundary_passes_only_envelope_via_stdin_without_shell(self):
        for adapter in (CLAUDE, CODEX):
            message = adapter.request(adapter.hook_context(fixture()), "context")
            completed = subprocess.CompletedProcess([], 0, '{"ok":true,"result":"fixture"}', "")
            with self.subTest(harness=adapter.HARNESS), \
                    patch.object(adapter, "resolve_worker", return_value=Path("/package/core/chronicle.py")), \
                    patch.object(adapter.subprocess, "run", return_value=completed) as process:
                result = adapter.run_core(message)
            call = process.call_args
            self.assertEqual((result, call.args[0], json.loads(call.kwargs["input"]), call.kwargs.get("shell", False)),
                             ("fixture", [sys.executable, "-B", "/package/core/chronicle.py"], message, False))

    def test_worker_timeout_is_explicit_failure(self):
        for adapter in (CLAUDE, CODEX):
            with self.subTest(harness=adapter.HARNESS), \
                    patch.object(adapter, "resolve_worker", return_value=WORKER), \
                    patch.object(adapter.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 2)):
                with self.assertRaisesRegex(adapter.Blocked, "worker_unavailable_or_invalid_reply"):
                    adapter.run_core(adapter.request(adapter.hook_context(fixture()), "checkpoint"))


class PackageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    def test_resolver_uses_own_package_prefers_core_and_never_searches_cwd(self):
        for adapter in (CLAUDE, CODEX):
            package = self.root / adapter.HARNESS
            script = package / "adapters" / adapter.HARNESS / "hook.py"
            script.parent.mkdir(parents=True)
            legacy = package / "skill/session-chronicle/scripts/chronicle.py"
            legacy.parent.mkdir(parents=True)
            legacy.touch()
            native = package / "core/chronicle.py"
            native.parent.mkdir()
            sibling = package.parent / (adapter.HARNESS + "-sibling") / "core/chronicle.py"
            sibling.parent.mkdir(parents=True)
            sibling.touch()
            with self.subTest(harness=adapter.HARNESS), patch.object(adapter, "__file__", str(script)):
                self.assertEqual(adapter.resolve_worker(), legacy)
                native.touch()
                self.assertEqual(adapter.resolve_worker(), native)
                native.unlink()
                legacy.unlink()
                with self.assertRaisesRegex(adapter.Blocked, "worker_missing"):
                    adapter.resolve_worker()

    def test_registration_fragments_are_inert_and_use_only_documented_command_fields(self):
        for adapter in (CLAUDE, CODEX):
            path = ROOT / "adapters" / adapter.HARNESS / "hooks.fragment.json"
            fragment = json.loads(path.read_text())
            with self.subTest(harness=adapter.HARNESS):
                self.assertEqual(set(fragment), {"hooks"})
                for groups in fragment["hooks"].values():
                    for group in groups:
                        self.assertTrue(set(group) <= {"matcher", "hooks"})
                        for handler in group["hooks"]:
                            self.assertEqual(set(handler), {"type", "command", "timeout"})
                            self.assertEqual(handler["type"], "command")
                            self.assertIn("/ABSOLUTE/PACKAGE_ROOT/adapters/", handler["command"])

    def test_cli_missing_context_has_no_sibling_or_pending_side_effects(self):
        sibling = self.root / "sibling"
        pending = sibling / "docs/.drafts/pending/batch.json"
        pending.parent.mkdir(parents=True)
        pending.write_text("evidence must survive\n")
        before = snapshot(self.root)
        for adapter in (CLAUDE, CODEX):
            process = subprocess.run([sys.executable, "-B", adapter.__file__], input='{"hook_event_name":"PreToolUse"}',
                                     cwd=sibling, capture_output=True, text=True, check=False)
            with self.subTest(harness=adapter.HARNESS):
                self.assertEqual((process.returncode, json.loads(process.stdout)["hookSpecificOutput"]["permissionDecision"]),
                                 (2, "deny"))
                self.assertEqual(snapshot(self.root), before)

    def test_registered_event_denies_malformed_or_mismatched_stdin(self):
        for adapter in (CLAUDE, CODEX):
            for payload in ("not-json", "[]", '{"hook_event_name":"SessionEnd"}'):
                process = subprocess.run([sys.executable, "-B", adapter.__file__, "--event", "PreToolUse"],
                                         input=payload, cwd=self.root, capture_output=True, text=True, check=False)
                with self.subTest(harness=adapter.HARNESS, payload=payload):
                    self.assertEqual((process.returncode,
                                      json.loads(process.stdout)["hookSpecificOutput"]["permissionDecision"]), (2, "deny"))
                    self.assertNotIn("Traceback", process.stderr)


@unittest.skipUnless(WORKER.is_file(), "Shared core not present; mocked boundary checks are not core integration")
class RealCoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(dir="/tmp/opencode")
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "AGENTS.md").write_text("---\ndocs-root: docs\n---\n")
        self.sibling = self.root / "sibling"
        self.sibling.mkdir()
        (self.sibling / "settings.json").write_text('{"owned":"by sibling"}\n')
        self.sibling_before = snapshot(self.sibling)

    def run_hook(self, adapter, payload, *options):
        return subprocess.run([sys.executable, "-B", adapter.__file__, *options],
                              input=json.dumps(payload), cwd=self.sibling,
                              capture_output=True, text=True, check=False)

    def test_real_fresh_start_injects_untrusted_index_not_semantic_context(self):
        for adapter in (CLAUDE, CODEX):
            process = self.run_hook(adapter, fixture("SessionStart", cwd=str(self.project)))
            with self.subTest(harness=adapter.HARNESS):
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                output = json.loads(process.stdout)
                self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SessionStart")
                self.assertIn("<chronicle-untrusted>", output["hookSpecificOutput"]["additionalContext"])
                self.assertNotIn("identity", output["hookSpecificOutput"]["additionalContext"])
                self.assertEqual(snapshot(self.sibling), self.sibling_before)

    def test_real_codex_unknown_start_orients_without_mutation(self):
        before = snapshot(self.project)
        process = self.run_hook(CODEX, fixture("SessionStart", cwd=str(self.project)))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("checkpoint_actor_not_primary", json.loads(process.stdout)["systemMessage"])
        self.assertEqual(snapshot(self.project), before)
        self.assertEqual(snapshot(self.sibling), self.sibling_before)

    def test_real_prompt_retrieval_survives_missing_capture_origin_and_id(self):
        topic = self.project / "docs/topics/routing.md"
        topic.parent.mkdir(parents=True)
        topic.write_text("---\ntype: topic\nnote-kind: atomic\ntitle: Routing\nstatus: active\n---\n"
                         "# Routing\nQuasar routing preserves isolated request ownership.\n")
        before = snapshot(self.project)
        for adapter in (CLAUDE, CODEX):
            process = self.run_hook(adapter, fixture("UserPromptSubmit", cwd=str(self.project),
                                                     prompt="Explain quasar routing"))
            with self.subTest(harness=adapter.HARNESS):
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                output = json.loads(process.stdout)
                self.assertIn("systemMessage", output)
                self.assertNotIn("decision", output)
                self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
                injected = output["hookSpecificOutput"]["additionalContext"]
                self.assertIn("<chronicle-untrusted>", injected)
                self.assertIn("Quasar routing", injected)
                self.assertEqual(snapshot(self.project), before)
                self.assertEqual(snapshot(self.sibling), self.sibling_before)

    def test_real_primary_write_is_recorded_once_and_child_is_excluded(self):
        payload = write_fixture("PostToolUse", cwd=str(self.project))
        for _ in range(2):
            process = self.run_hook(CLAUDE, payload)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        child = write_fixture("PostToolUse", cwd=str(self.project), agent_id="child-24")
        child["tool_use_id"] = "child-call-24"
        process = self.run_hook(CLAUDE, child)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("actor_not_primary", json.loads(process.stdout)["systemMessage"])
        records = [json.loads(line) for path in (self.project / "docs/.drafts").glob("*.draft.jsonl")
                   for line in path.read_text().splitlines() if line]
        self.assertEqual([(record["event_id"], record["operation"], record["origin"]) for record in records],
                         [("tool-call-17", "files.write", "unknown")])
        self.assertEqual(snapshot(self.sibling), self.sibling_before)

    def test_real_unknown_codex_guard_allows_normal_work_and_denies_memory_mutation(self):
        before = snapshot(self.project)
        for target, expected in (("src/fixture.py", 0), ("docs/topics/fixture.md", 2)):
            payload = fixture(cwd=str(self.project), tool_name="apply_patch", tool_input={
                "command": "*** Begin Patch\n*** Add File: " + target + "\n+fixture\n*** End Patch"})
            process = self.run_hook(CODEX, payload)
            with self.subTest(target=target):
                self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
                if expected:
                    self.assertEqual(json.loads(process.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
                self.assertEqual(snapshot(self.project), before)

    def test_real_diagnostic_index_is_nonmutating_and_has_no_context_fallback(self):
        before = snapshot(self.project)
        for adapter in (CLAUDE, CODEX):
            process = self.run_hook(adapter, fixture("SessionEnd", cwd=str(self.project)), "--diagnostic", "index")
            with self.subTest(harness=adapter.HARNESS):
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertIn("<chronicle-untrusted>", json.loads(process.stdout)["result"])
                rejected = self.run_hook(adapter, fixture("SessionEnd", cwd=str(self.project)),
                                         "--diagnostic", "context")
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(snapshot(self.project), before)

    def test_real_core_claude_guard_rejects_pending_evidence_overwrite(self):
        pending = self.project / "docs/.drafts/pending/fixture.json"
        pending.parent.mkdir(parents=True)
        pending.write_text('{"evidence":"retain exactly"}\n')
        before = snapshot(self.project)
        payload = fixture(cwd=str(self.project), tool_name="Write", tool_input={
            "file_path": str(pending), "content": "destroyed"})
        process = self.run_hook(CLAUDE, payload)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(snapshot(self.project), before)
        self.assertEqual(snapshot(self.sibling), self.sibling_before)

    def test_real_diagnostics_never_accept_model_session_identity(self):
        before = snapshot(self.project)
        for adapter in (CLAUDE, CODEX):
            process = self.run_hook(adapter, fixture("SessionEnd", cwd=str(self.project)),
                                    "--diagnostic", "index", "--arguments", '{"session_id":"forged"}')
            with self.subTest(harness=adapter.HARNESS):
                self.assertEqual(process.returncode, 1)
                self.assertEqual(json.loads(process.stdout)["error"]["code"], "invalid_read_arguments")
        self.assertEqual(snapshot(self.project), before)

    def test_real_checkpoint_failure_preserves_corrupt_pending_evidence(self):
        pending = self.project / "docs/.drafts/pending/2026-10-15--evidence-fixture.jsonl"
        pending.parent.mkdir(parents=True)
        evidence = b"malformed pending evidence must survive\n"
        pending.write_bytes(evidence)
        for adapter, event in ((CLAUDE, "Stop"), (CODEX, "SessionEnd")):
            process = self.run_hook(adapter, fixture(event, cwd=str(self.project)))
            with self.subTest(harness=adapter.HARNESS):
                self.assertEqual(process.returncode, 0 if event == "Stop" else 1, process.stdout + process.stderr)
                self.assertIn("systemMessage", json.loads(process.stdout))
                self.assertNotIn("decision", json.loads(process.stdout))
                self.assertEqual(pending.read_bytes(), evidence)
                self.assertFalse(list((self.project / "docs/sessions").glob("*.md")))
                self.assertEqual(snapshot(self.sibling), self.sibling_before)

    def test_real_checkpoint_publishes_seeded_fixture_without_sibling_effects(self):
        # A trusted neutral fixture seeds the worker; no native capture claim.
        context = CLAUDE.hook_context(fixture("Stop", cwd=str(self.project)))
        message = CLAUDE.request(context, "capture", {
            "operation": "files.write", "event_id": "fixture-native-call-23", "status": "completed",
            "origin": "user", "path": "src/fixture.py"})
        seed = subprocess.run([sys.executable, "-B", str(WORKER)], input=json.dumps(message),
                              cwd=self.sibling, capture_output=True, text=True, check=False)
        self.assertEqual(seed.returncode, 0, seed.stdout + seed.stderr)
        process = self.run_hook(CLAUDE, fixture("Stop", cwd=str(self.project)))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        records = list((self.project / "docs/sessions").glob("*.md"))
        self.assertTrue(records)
        self.assertIn("fixture-native-call-23", "\n".join(path.read_text() for path in records))
        self.assertEqual(snapshot(self.sibling), self.sibling_before)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""One-shot Claude command-hook bridge. See README.md for qualification limits."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


HARNESS = "claude-code"
DIAGNOSTIC_OPERATIONS = ("index", "find", "recall", "backlinks", "audit")
TOOL_OPERATIONS = {"Write": "files.write", "Edit": "files.edit", "Bash": "process.exec"}


class Blocked(Exception):
    """A contract or worker failure with a content-free diagnostic code."""


def text_field(payload, key):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise Blocked("missing_or_invalid_" + key)
    return value


def hook_context(payload):
    if not isinstance(payload, dict):
        raise Blocked("invalid_hook_object")
    session_id = text_field(payload, "session_id")
    workspace = text_field(payload, "cwd")
    if not Path(workspace).is_absolute():
        raise Blocked("workspace_not_absolute")
    role = "primary"
    if "agent_id" in payload:
        text_field(payload, "agent_id")
        role = "delegated"
    # Published BaseHookInput explicitly says agent_id is absent on main.
    return {"harness": HARNESS, "session_id": session_id, "workspace": workspace, "role": role}


def request(context, operation, arguments=None):
    return {"schema_version": 1, "operation": operation,
            "context": context, "arguments": arguments or {}}


def resolve_worker():
    root = Path(__file__).resolve().parents[2]
    for candidate in (root / "core/chronicle.py",
                      root / "skill/session-chronicle/scripts/chronicle.py"):
        if candidate.is_file():
            return candidate
    raise Blocked("worker_missing")


def run_core(message):
    try:
        completed = subprocess.run(
            [sys.executable, "-B", str(resolve_worker())], input=json.dumps(message),
            text=True, capture_output=True, timeout=20, check=False,
            cwd=message["context"]["workspace"],
        )
        reply = json.loads(completed.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise Blocked("worker_unavailable_or_invalid_reply") from None
    if not isinstance(reply, dict) or reply.get("ok") is not True or completed.returncode != 0:
        error = reply.get("error", {}) if isinstance(reply, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", code):
            code = "worker_failed"
        raise Blocked(code)
    if not isinstance(reply.get("result"), (dict, str)):
        raise Blocked("invalid_worker_result")
    return reply["result"]


def tool_input(payload):
    value = payload.get("tool_input")
    if not isinstance(value, dict):
        raise Blocked("invalid_tool_input")
    return value


def guard_arguments(payload, phase):
    name = text_field(payload, "tool_name")
    values = tool_input(payload)
    if name not in ("Write", "Edit"):
        return None
    arguments = {"phase": phase, "path": text_field(values, "file_path")}
    if name == "Write":
        if not isinstance(values.get("content"), str):
            raise Blocked("invalid_content")
        return {**arguments, "kind": "replace", "content": values["content"]}
    if not isinstance(values.get("new_string"), str):
        raise Blocked("invalid_new_string")
    replace_all = values.get("replace_all", False)
    if not isinstance(replace_all, bool):
        raise Blocked("invalid_replace_all")
    return {**arguments, "kind": "edit", "old_text": text_field(values, "old_string"),
            "new_text": values["new_string"], "replace_all": replace_all}


def capture_arguments(payload):
    """Translate documented fields; unknown origin remains visibly unknown."""
    event = text_field(payload, "hook_event_name")
    if event == "UserPromptSubmit":
        return {"operation": "prompt.submit", "event_id": text_field(payload, "prompt_id"),
                "text": text_field(payload, "prompt"), "status": "completed", "origin": "unknown"}
    if event not in ("PostToolUse", "PostToolUseFailure"):
        raise Blocked("unsupported_capture_event")
    name = text_field(payload, "tool_name")
    if name not in TOOL_OPERATIONS:
        raise Blocked("unsupported_tool")
    values = tool_input(payload)
    arguments = {"operation": TOOL_OPERATIONS[name], "event_id": text_field(payload, "tool_use_id"),
                 "status": "error" if event == "PostToolUseFailure" else "completed", "origin": "unknown"}
    if name == "Bash":
        arguments.update(command=text_field(values, "command"), workdir=text_field(payload, "cwd"))
    else:
        arguments["path"] = text_field(values, "file_path")
    return arguments


def capture(payload, context):
    arguments = capture_arguments(payload)
    if context["role"] != "primary":
        raise Blocked("actor_not_primary")
    if arguments["status"] != "completed":
        raise Blocked("capture_failed_tool_excluded")
    if arguments["operation"] == "prompt.submit" and arguments["origin"] != "user":
        raise Blocked("native_origin_unproven")
    return run_core(request(context, "capture", arguments))


def attempt(message, diagnostics):
    try:
        return run_core(message)
    except Blocked as error:
        diagnostics.append(str(error))
        return None


def checkpoint(context, diagnostics):
    if context["role"] != "primary":
        diagnostics.append("checkpoint_actor_not_primary")
        return
    attempt(request(context, "checkpoint"), diagnostics)


def hook_output(event, diagnostics, result=None):
    output = {}
    if diagnostics:
        output["systemMessage"] = "Chronicle diagnostic: " + ", ".join(diagnostics) + ". Pending evidence retained."
    if result is not None:
        if not isinstance(result, str):
            raise Blocked("invalid_read_result")
        output["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": result}
    return output


def observe_capture(payload, context, diagnostics):
    try:
        capture(payload, context)
    except Blocked as error:
        diagnostics.append(str(error))


def handle_hook(payload):
    context = hook_context(payload)
    event = text_field(payload, "hook_event_name")
    diagnostics = []
    if event == "SessionStart":
        checkpoint(context, diagnostics)
        result = attempt(request(context, "index"), diagnostics)
        return hook_output(event, diagnostics, result)
    if event == "PreToolUse":
        arguments = guard_arguments(payload, "pre")
        if arguments:
            run_core(request(context, "guard", arguments))
        return {}
    if event == "UserPromptSubmit":
        observe_capture(payload, context, diagnostics)
        result = attempt(request(context, "find", {
            "query": text_field(payload, "prompt"), "includeEvidence": False}), diagnostics)
        return hook_output(event, diagnostics, result)
    if event in ("PostToolUse", "PostToolUseFailure"):
        # Preserve eligible observations even if subsequent postflight lint fails.
        observe_capture(payload, context, diagnostics)
        if event == "PostToolUse":
            arguments = guard_arguments(payload, "post")
            if arguments:
                attempt(request(context, "guard", arguments), diagnostics)
        return hook_output(event, diagnostics)
    if event in ("Stop", "PreCompact", "SessionEnd"):
        checkpoint(context, diagnostics)
        if diagnostics and event in ("PreCompact", "SessionEnd"):
            # Claude discards PreCompact systemMessage; stderr is observational.
            raise Blocked(diagnostics[0])
        return hook_output(event, diagnostics)
    if event == "PostCompact":
        raise Blocked("use_session_start_compact_for_context")
    raise Blocked("unsupported_hook_event")


def failure_output(event, code, stop_active=False):
    reason = "Chronicle diagnostic: " + code + ". Pending evidence retained."
    if event == "PreToolUse":
        output = {"hookSpecificOutput": {"hookEventName": event,
                  "permissionDecision": "deny", "permissionDecisionReason": reason}}
        return output, 2, reason
    status = 1 if event in ("PreCompact", "PostCompact", "SessionEnd") else 0
    return {"systemMessage": reason}, status, reason


def diagnostic_request(payload, operation, arguments):
    context = hook_context(payload)
    # A fixture is not runtime authentication: diagnostics never mutate identity/state.
    context["role"] = "unknown"
    allowed = {"index": set(), "find": {"query", "includeEvidence"},
               "recall": {"slug", "scope"}, "backlinks": {"slug"}, "audit": {"mode"}}
    if operation not in allowed:
        raise Blocked("native_context_transport_required")
    if not isinstance(arguments, dict) or set(arguments) - allowed[operation]:
        raise Blocked("invalid_read_arguments")
    return request(context, operation, arguments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", help="Expected native event, fixed by the registration command")
    parser.add_argument("--diagnostic", choices=DIAGNOSTIC_OPERATIONS, help="Operator fixture diagnostic; not a native tool")
    parser.add_argument("--arguments", default="{}", help="Diagnostic arguments, never session identity")
    options = parser.parse_args()
    payload = {}
    try:
        payload = json.load(sys.stdin)
        if options.diagnostic:
            result = run_core(diagnostic_request(payload, options.diagnostic, json.loads(options.arguments)))
            output = {"ok": True, "result": result}
        else:
            if options.event and (not isinstance(payload, dict) or payload.get("hook_event_name") != options.event):
                raise Blocked("native_event_mismatch")
            if options.arguments != "{}":
                raise Blocked("arguments_require_diagnostic_mode")
            output = handle_hook(payload)
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (Blocked, ValueError) as error:
        code = str(error) if isinstance(error, Blocked) else "invalid_json"
        if options.diagnostic:
            print(json.dumps({"ok": False, "error": {"code": code, "message": "Fixture diagnostic blocked."}}))
            return 1
        event = options.event or (payload.get("hook_event_name") if isinstance(payload, dict) else None)
        active = isinstance(payload, dict) and payload.get("stop_hook_active") is True
        output, status, reason = failure_output(event, code, active)
        print(json.dumps(output))
        print(reason, file=sys.stderr)
        return status


if __name__ == "__main__":
    sys.exit(main())

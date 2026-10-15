#!/usr/bin/env python3
"""One-shot Codex command-hook bridge. See README.md for qualification limits."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


HARNESS = "codex"
DIAGNOSTIC_OPERATIONS = ("index", "find", "recall", "backlinks", "audit")


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
    role = "unknown"
    if "agent_id" in payload:
        text_field(payload, "agent_id")
        role = "delegated"
    elif payload.get("hook_event_name") in ("SessionEnd", "Interrupt"):
        # Only these events explicitly exclude subagents in the official docs.
        role = "primary"
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
            text=True, capture_output=True,
            timeout=2 if message["operation"] == "checkpoint" else 20, check=False,
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


def guard_arguments(payload, phase):
    name = text_field(payload, "tool_name")
    values = payload.get("tool_input")
    if not isinstance(values, dict):
        raise Blocked("invalid_tool_input")
    if name != "apply_patch":
        return None
    return {"kind": "patch", "patch": text_field(values, "command"), "phase": phase}


def capture_arguments(payload):
    event = text_field(payload, "hook_event_name")
    if event == "UserPromptSubmit":
        text_field(payload, "turn_id")
        # A turn id is not documented as a stable, unique prompt event id.
        raise Blocked("native_prompt_event_id_and_origin_unproven")
    if event != "PostToolUse":
        raise Blocked("unsupported_capture_event")
    text_field(payload, "tool_use_id")
    # PostToolUse also fires after nonzero exits; tool_response has no status schema.
    raise Blocked("native_tool_status_unproven")


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


def capture_diagnostic(payload):
    try:
        capture_arguments(payload)
    except Blocked as error:
        return str(error)
    raise Blocked("unsupported_capture_event")


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
        diagnostics.append(capture_diagnostic(payload))
        result = attempt(request(context, "find", {
            "query": text_field(payload, "prompt"), "includeEvidence": False}), diagnostics)
        return hook_output(event, diagnostics, result)
    if event == "PostToolUse":
        return hook_output(event, [capture_diagnostic(payload)])
    if event in ("Stop", "PreCompact", "SessionEnd", "Interrupt"):
        checkpoint(context, diagnostics)
        if diagnostics and event in ("SessionEnd", "Interrupt"):
            raise Blocked(diagnostics[0])
        return hook_output(event, diagnostics)
    if event == "PostCompact":
        # This event cannot return additionalContext under the documented contract.
        raise Blocked("use_session_start_compact_for_context")
    raise Blocked("unsupported_hook_event")


def failure_output(event, code, stop_active=False):
    reason = "Chronicle diagnostic: " + code + ". Pending evidence retained."
    if event == "PreToolUse":
        output = {"hookSpecificOutput": {"hookEventName": event,
                  "permissionDecision": "deny", "permissionDecisionReason": reason}}
        return output, 2, reason
    status = 1 if event in ("SessionEnd", "Interrupt") else 0
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

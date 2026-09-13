import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lint-agents.py"
SPEC = importlib.util.spec_from_file_location("lint_agents", SCRIPT)
LINTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINTER)


class LintAgentsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.skill = self.repo / "skill" / "example" / "SKILL.md"
        self.command = self.repo / "command" / "example.md"
        self.write(self.skill, "name: example\ndescription: Explain example usage.")
        self.write(self.command, "description: Run the example skill.")

    def write(self, path, metadata, body="Use the skill tool."):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\n{metadata}\n---\n{body}\n", encoding="utf-8")

    def run_linter(self, *arguments):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo), *arguments],
            capture_output=True, text=True, check=False,
        )
        self.assertNotIn("Traceback", result.stderr)
        return result

    def assert_error(self, text):
        result = self.run_linter()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(text, result.stderr)

    def test_clean_singular_tree(self):
        result = self.run_linter()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 commands, 1 skills", result.stdout)

    def test_installed_and_library_roots_are_excluded(self):
        for relative in (".opencode/skills/broken/SKILL.md", "skills/broken/SKILL.md",
                         ".opencode/command/broken.md", "agents/broken.md", "rosters/broken.yaml"):
            self.write(self.repo / relative, "invalid: [")
        self.assertEqual(self.run_linter().returncode, 0)

    def test_missing_roots(self):
        for root in ("skill", "command"):
            with self.subTest(root=root):
                path = self.repo / root
                moved = self.repo / f"saved-{root}"
                path.rename(moved)
                self.assert_error("cannot read required directory")
                moved.rename(path)

    def test_empty_roots(self):
        self.skill.unlink()
        self.skill.parent.rmdir()
        self.command.unlink()
        self.assert_error("no skill directories found")
        self.assert_error("no command definitions found")

    def test_missing_skill_definition(self):
        self.skill.unlink()
        self.assert_error("cannot read definition")

    def test_bad_frontmatter(self):
        for content in ("No frontmatter", "---\ninvalid: [\n---\n", "---\n- item\n---\n",
                        "---\nnull\n---\n", "---\n1: value\n---\n"):
            with self.subTest(content=content):
                self.skill.write_text(content, encoding="utf-8")
                self.assert_error("frontmatter")

    def test_invalid_field_types(self):
        for field in ("name: []", "description: []", "description: true", "description: '  '",
                      "user-invocable: 'false'", "allowed-tools: {}", "metadata: []",
                      "metadata: {key: 2}"):
            with self.subTest(field=field):
                defaults = {"name": "example", "description": "Explain example usage."}
                defaults.pop(field.split(":", 1)[0], None)
                self.write(self.skill, "\n".join(f"{key}: {value}" for key, value in defaults.items())
                           + "\n" + field)
                self.assert_error(f"`{field.split(':', 1)[0]}`")

    def test_command_description_types(self):
        for metadata in ("{}", "description: null", "description: 5", "description: {}",
                         "description: ' '"):
            with self.subTest(metadata=metadata):
                self.write(self.command, metadata)
                self.assert_error("`description`")

    def test_name_mismatch(self):
        self.write(self.skill, "name: different\ndescription: Explain usage.")
        self.assert_error("but the directory is")

    def test_invalid_skill_names(self):
        for name in ("Uppercase", "two--hyphens", "-leading", "trailing-", "under_score", "a" * 65):
            with self.subTest(name=name):
                self.write(self.skill, f"name: {name}\ndescription: Explain usage.")
                self.assert_error("single separating hyphens")

    def test_orphan_command(self):
        self.command.rename(self.command.with_name("orphan.md"))
        self.assert_error("no matching skill 'orphan'")

    def test_missing_shim_warning_and_quiet(self):
        self.write(self.repo / "skill" / "extra" / "SKILL.md",
                   "name: extra\ndescription: Explain extra usage.")
        result = self.run_linter()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no command shim in command/", result.stdout)
        quiet = self.run_linter("-q")
        self.assertEqual(quiet.returncode, 0, quiet.stderr)
        self.assertNotIn("no command shim", quiet.stdout)
        self.assertIn("1 warning(s)", quiet.stdout)

    def test_non_user_invocable_skill_needs_no_shim(self):
        self.write(self.repo / "skill" / "extra" / "SKILL.md",
                   "name: extra\ndescription: Explain extra usage.\nuser-invocable: false")
        result = self.run_linter()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 warning(s)", result.stdout)

    def test_duplicate_and_unhashable_yaml_keys(self):
        for metadata in ("name: example\nname: other", "metadata: {key: one, key: two}",
                         "? [one, two]\n: value"):
            with self.subTest(metadata=metadata):
                self.write(self.skill, metadata)
                self.assert_error("frontmatter does not parse")

    def test_grep_in_skill_and_command_bash_fences(self):
        for path, metadata in ((self.skill, "name: example\ndescription: Explain usage."),
                               (self.command, "description: Run example.")):
            with self.subTest(path=path):
                self.write(path, metadata, "```bash\ncat file | grep word\n```")
                self.assert_error("workspace rule")
                self.write(path, metadata)

    def test_rg_prose_and_bash_comments_are_allowed(self):
        self.write(self.skill, "name: example\ndescription: Explain usage.\nallowed-tools: Skill(other)",
                   "Use grep in prose.\n```bash\n# grep example\nrg example file\n```")
        self.assertEqual(self.run_linter().returncode, 0)

    def test_grep_in_shell_control_command_positions(self):
        for command in (
            "if grep word file; then :; fi",
            "while grep word file; do :; done",
            "until grep word file; do :; done",
            "! grep word file",
            "{ grep word file; }",
            "if true; then grep word file; fi",
            "while true; do grep word file; done",
            "if false; then :; else grep word file; fi",
            "if false; then :; elif grep word file; then :; fi",
            "if ! grep word file; then :; fi",
            "then grep word file",
            "do grep word file",
            "else grep word file",
            "true && { ! grep word file; }",
            "(grep word file)",
            "result=$(grep word file)",
            'echo "quoted prose"; if grep word file; then :; fi',
        ):
            with self.subTest(command=command):
                report = LINTER.Report()
                LINTER.check_no_grep(self.skill, f"```bash\n{command}\n```", report)
                self.assertEqual(len(report.errors), 1, command)

    def test_grep_arguments_and_quoted_prose_are_not_commands(self):
        for command in (
            "echo if grep word file",
            "printf '%s' 'while grep word file; then grep word file'",
            'echo "! grep word file; { grep word file; }"',
            'echo "say \\"if grep\\"; else grep"',
            "echo text # ; grep word file",
            "# if grep word file",
            "echo grep",
            "echo if 'condition' grep",
            "echo \\; grep word file",
            "grep-helper word file",
            "grep_count=1",
            "xgrep word file",
            "rg word file",
        ):
            with self.subTest(command=command):
                report = LINTER.Report()
                LINTER.check_no_grep(self.skill, f"```bash\n{command}\n```", report)
                self.assertEqual(report.errors, [], command)

    def test_invalid_utf8(self):
        self.skill.write_bytes(b"\xff")
        self.assert_error("cannot read definition")

    def test_io_errors_have_clean_diagnostics(self):
        for target in ("read_text", "iterdir"):
            with self.subTest(target=target), patch.object(Path, target, side_effect=PermissionError("denied")):
                stderr = io.StringIO()
                with patch.object(sys, "argv", [str(SCRIPT), "--repo", str(self.repo)]), \
                        contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(LINTER.main(), 1)
                self.assertIn("denied", stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_missing_dependency_is_actionable(self):
        stderr = io.StringIO()
        with patch.object(LINTER, "yaml", None), patch.object(sys, "argv", [str(SCRIPT)]), \
                contextlib.redirect_stderr(stderr):
            self.assertEqual(LINTER.main(), 1)
        self.assertIn("python3 -m pip install -r scripts/requirements-lint.txt", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

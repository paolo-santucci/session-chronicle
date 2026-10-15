"""Fixture-only coverage for the standalone installer safety boundaries."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

class InstallLocalTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(dir="/tmp/opencode" if Path("/tmp/opencode").is_dir() else None)
        self.root = Path(self.tempdir.name); self.repo = self.root / "fixture"
        for directory in ("scripts", "skill/session-chronicle", "command", "adapters/opencode", "adapters/shared", "skills/neutral"):
            (self.repo / directory).mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / "scripts/install-local.sh", self.repo / "scripts")
        for name in ("index.ts", "package.json", "bun.lock", "tsconfig.json", "README.md", "plugin.yaml"): (self.repo / name).write_text("fixture\n")
        (self.repo / "skill/session-chronicle/SKILL.md").write_text("legacy\n")
        (self.repo / "command/session-chronicle.md").write_text("command\n")
        (self.repo / "adapters/opencode/index.ts").write_text("adapter\n")
        (self.repo / "adapters/shared/worker-client.ts").write_text("shared\n")
        (self.repo / "skills/neutral/SKILL.md").write_text("neutral\n")
        self.bin = self.root / "bin"; self.bin.mkdir()
        self.bun_log = self.root / "bun.log"
        self.bun = self.bin / "bun"; self.bun.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > \"$BUN_LOG\"\n[ \"$1\" = install ] && exit 0\nexit 1\n"); self.bun.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "XDG_CONFIG_HOME": str(self.root / "xdg"), "BUN_LOG": str(self.bun_log)}
        self.target = self.root / "target"; self.target.mkdir()
    def tearDown(self): self.tempdir.cleanup()
    def run_installer(self, *args): return subprocess.run(["bash", str(self.repo / "scripts/install-local.sh"), *args], cwd=self.repo, env=self.env, text=True, capture_output=True)
    def test_copies_portable_adapters_but_keeps_native_legacy_surface(self):
        self.assertEqual(self.run_installer(str(self.target)).returncode, 0)
        module = self.target / ".opencode/session-chronicle"
        self.assertTrue((module / "adapters/opencode/index.ts").is_file())
        self.assertTrue((module / "adapters/shared/worker-client.ts").is_file())
        self.assertTrue((module / "bun.lock").is_file())
        self.assertEqual(self.bun_log.read_text().strip(), "install --production --frozen-lockfile --ignore-scripts")
        self.assertTrue((module / "skills/neutral/SKILL.md").is_file())
        self.assertTrue((self.target / ".opencode/skills/session-chronicle/SKILL.md").is_file())
        self.assertFalse((self.target / ".opencode/skills/neutral").exists())
    def test_actual_uat_manifest_blocks_even_without_chronicle_plugin(self):
        manifest = self.target / ".uat/deployments/opencode.json"; manifest.parent.mkdir(parents=True)
        manifest.write_text('{"schema-version":1,"harness":"opencode","replace_paths":["plugins","skills"],"plugins":{"other":"1"}}')
        result = self.run_installer(str(self.target), "--force")
        self.assertNotEqual(result.returncode, 0); self.assertIn("UAT owns", result.stderr)
        self.assertFalse((self.target / ".opencode/session-chronicle").exists())
    def test_malformed_or_symlink_uat_manifest_blocks(self):
        manifest = self.target / ".uat/deployments/opencode.json"; manifest.parent.mkdir(parents=True); manifest.write_text("not json")
        self.assertIn("malformed UAT", self.run_installer(str(self.target)).stderr)
        manifest.unlink(); manifest.symlink_to(self.root / "missing-manifest")
        self.assertIn("manifest symlink", self.run_installer(str(self.target)).stderr)
    def test_unidentified_and_modified_owned_paths_require_force(self):
        shim = self.target / ".opencode/plugins/session-chronicle.ts"; shim.parent.mkdir(parents=True); shim.write_text("author content\n")
        self.assertIn("collision or local modification", self.run_installer(str(self.target)).stderr)
        shim.unlink(); self.assertEqual(self.run_installer(str(self.target)).returncode, 0)
        module_file = self.target / ".opencode/session-chronicle/index.ts"; module_file.write_text("locally modified\n")
        self.assertIn("collision or local modification", self.run_installer(str(self.target)).stderr)
    def test_failed_dependency_install_preserves_existing_and_unrelated(self):
        existing = self.target / ".opencode/session-chronicle"; existing.mkdir(parents=True); (existing / "keep").write_text("old")
        unrelated = self.target / ".opencode/skills/unrelated"; unrelated.mkdir(parents=True); (unrelated / "keep").write_text("yes")
        self.bun.write_text("#!/usr/bin/env bash\nexit 7\n"); self.bun.chmod(0o755)
        result = self.run_installer(str(self.target), "--force")
        self.assertIn("target was not modified", result.stderr); self.assertEqual((existing / "keep").read_text(), "old"); self.assertEqual((unrelated / "keep").read_text(), "yes")
    def test_shim_install_failure_restores_previous_shim_and_removes_new_module(self):
        shim = self.target / ".opencode/plugins/session-chronicle.ts"; shim.parent.mkdir(parents=True); shim.write_text("author content\n")
        fake_mv = self.bin / "mv"
        fake_mv.write_text("#!/usr/bin/env bash\ncase \"$1\" in *session-chronicle-install.*/plugins/session-chronicle.ts) exit 9;; esac\nexec /usr/bin/mv \"$@\"\n")
        fake_mv.chmod(0o755)
        result = self.run_installer(str(self.target), "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(shim.read_text(), "author content\n")
        self.assertFalse((self.target / ".opencode/session-chronicle").exists())
    def test_term_after_first_replacement_restores_old_paths_and_fails(self):
        module = self.target / ".opencode/session-chronicle"; module.mkdir(parents=True); (module / "old").write_text("module\n")
        shim = self.target / ".opencode/plugins/session-chronicle.ts"; shim.parent.mkdir(parents=True); shim.write_text("shim\n")
        fake_mv = self.bin / "mv"
        fake_mv.write_text("#!/usr/bin/env bash\ncase \"$1\" in *session-chronicle-install.*/session-chronicle) kill -TERM \"$PPID\";; esac\nexec /usr/bin/mv \"$@\"\n")
        fake_mv.chmod(0o755)
        result = self.run_installer(str(self.target), "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((module / "old").read_text(), "module\n")
        self.assertEqual(shim.read_text(), "shim\n")
    def test_term_after_backup_before_replacement_restores_old_module(self):
        module = self.target / ".opencode/session-chronicle"; module.mkdir(parents=True); (module / "old").write_text("module\n")
        fake_mv = self.bin / "mv"
        fake_mv.write_text("#!/usr/bin/env bash\ncase \"$2\" in *session-chronicle-install-backup.*/0) kill -TERM \"$PPID\";; esac\nexec /usr/bin/mv \"$@\"\n")
        fake_mv.chmod(0o755)
        result = self.run_installer(str(self.target), "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((module / "old").read_text(), "module\n")
        self.assertFalse((module / "session-chronicle").exists())
    def test_failed_signal_rollback_retains_backup(self):
        module = self.target / ".opencode/session-chronicle"; module.mkdir(parents=True); (module / "old").write_text("module\n")
        fake_mv = self.bin / "mv"
        fake_mv.write_text("#!/usr/bin/env bash\ncase \"$1\" in *session-chronicle-install.*/session-chronicle) kill -TERM \"$PPID\";; *session-chronicle-install-backup.*) exit 8;; esac\nexec /usr/bin/mv \"$@\"\n")
        fake_mv.chmod(0o755)
        result = self.run_installer(str(self.target), "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback incomplete", result.stderr)
        self.assertTrue(list((self.target / ".opencode").glob(".session-chronicle-install-backup.*")))
    def test_failed_destination_removal_retains_backup_without_nested_restore(self):
        module = self.target / ".opencode/session-chronicle"; module.mkdir(parents=True); (module / "old").write_text("module\n")
        fake_mv = self.bin / "mv"
        fake_mv.write_text("#!/usr/bin/env bash\ncase \"$1\" in *session-chronicle-install.*/session-chronicle) kill -TERM \"$PPID\";; esac\nexec /usr/bin/mv \"$@\"\n")
        fake_mv.chmod(0o755)
        fake_rm = self.bin / "rm"
        fake_rm.write_text("#!/usr/bin/env bash\ncase \"$2\" in */.opencode/session-chronicle) exit 9;; esac\nexec /usr/bin/rm \"$@\"\n")
        fake_rm.chmod(0o755)
        result = self.run_installer(str(self.target), "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback incomplete", result.stderr)
        self.assertFalse((module / "session-chronicle").exists())
        backups = list((self.target / ".opencode").glob(".session-chronicle-install-backup.*"))
        self.assertEqual((backups[0] / "0/old").read_text(), "module\n")

if __name__ == "__main__": unittest.main()

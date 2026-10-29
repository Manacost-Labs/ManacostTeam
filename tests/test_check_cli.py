import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check as checks


class CheckCLITests(unittest.TestCase):
    def invoke(self, *arguments):
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return checks.main(list(arguments))

    def test_dry_run_and_list_never_launch_checks_or_require_installed_tools(self):
        with (
            patch.object(checks.subprocess, "run") as run,
            patch.object(checks.shutil, "which") as which,
        ):
            self.assertEqual(self.invoke("--dry-run", *checks.CHECKS), 0)
            self.assertEqual(self.invoke("--list"), 0)
        run.assert_not_called()
        which.assert_not_called()

    def test_registered_test_patterns_match_existing_files(self):
        # A renamed test directory/pattern must not turn a check into "Ran 0 tests".
        for area, (_, directory, commands) in checks.CHECKS.items():
            cwd = ROOT / directory
            with self.subTest(area=area):
                self.assertTrue(cwd.is_dir())
                for command in commands:
                    if "discover" not in command:
                        continue
                    start = cwd / command[command.index("-s") + 1]
                    pattern = command[command.index("-p") + 1]
                    self.assertTrue(
                        list(start.glob(pattern)), f"{area}: {start}/{pattern}"
                    )

    def test_invalid_scope_is_rejected_before_any_valid_scope_runs(self):
        with patch.object(checks.subprocess, "run") as run:
            for arguments in ((), ("context", "typo"), ("--list", "context")):
                with (
                    self.subTest(arguments=arguments),
                    self.assertRaises(SystemExit) as error,
                ):
                    self.invoke(*arguments)
                self.assertEqual(error.exception.code, 2)
        run.assert_not_called()

    def test_each_scope_runs_in_its_own_directory_with_argument_vector(self):
        with patch.object(
            checks.subprocess, "run", return_value=Mock(returncode=0)
        ) as run:
            self.assertEqual(self.invoke("context", "translate", "context"), 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            [call.kwargs["cwd"] for call in run.call_args_list],
            [ROOT, ROOT / "translate"],
        )
        for call in run.call_args_list:
            self.assertEqual(
                Path(call.args[0][0]).resolve(), Path(sys.executable).resolve()
            )
            self.assertIn("discover", call.args[0])
            self.assertFalse(call.kwargs.get("shell", False))

    def test_failure_stops_remaining_commands_and_propagates_exit_code(self):
        with patch.object(
            checks.subprocess, "run", return_value=Mock(returncode=7)
        ) as run:
            self.assertEqual(self.invoke("install", "server"), 7)
        self.assertEqual(run.call_count, 1)

    def test_missing_tool_and_launch_error_are_failures(self):
        with (
            patch.object(checks.shutil, "which", return_value=None),
            patch.object(checks.subprocess, "run") as run,
        ):
            self.assertEqual(self.invoke("xml"), 127)
        run.assert_not_called()
        with patch.object(
            checks.subprocess, "run", side_effect=OSError("cannot start")
        ):
            self.assertEqual(self.invoke("context"), 1)

    def test_external_tool_uses_resolved_path_including_spaces(self):
        executable = "C:/Program Files/nodejs/pnpm.cmd"
        with (
            patch.object(checks.shutil, "which", return_value=executable),
            patch.object(
                checks.subprocess, "run", return_value=Mock(returncode=0)
            ) as run,
        ):
            self.assertEqual(self.invoke("xml"), 0)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0], [executable, "run", "typecheck"]
        )
        self.assertEqual(run.call_args_list[1].args[0], [executable, "run", "test"])

    def test_cli_runs_real_context_tests_from_outside_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/check.py"), "context"],
                cwd=temporary,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ran ", result.stderr)
        self.assertIn("OK", result.stderr)

    def test_list_uses_utf8_even_with_ascii_console(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/check.py"), "--list"],
            env={**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"},
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertIn("Серверный API", result.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

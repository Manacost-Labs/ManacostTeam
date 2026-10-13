import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    shutil.which("php"), "PHP CLI is not installed; WordPress contract harness skipped"
)
class WordPressPluginTests(unittest.TestCase):
    def test_plugin_syntax_and_capabilities_nonces_output_contract(self):
        for args in (
            [
                "php",
                "-l",
                str(ROOT / "integrations/wordpress/manacost-team/manacost-team.php"),
            ],
            ["php", str(ROOT / "tests/wordpress_plugin.php")],
        ):
            process = subprocess.run(args, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

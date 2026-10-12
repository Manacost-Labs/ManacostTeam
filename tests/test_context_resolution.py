import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from resolve_context import load_catalog, resolve_context


class ContextResolutionTests(unittest.TestCase):
    def test_each_game_resolves_in_both_modes_with_each_profile(self):
        games, _ = load_catalog(ROOT, "games")
        expected = {
            "hearthstone", "league-of-legends", "world-of-warcraft",
            "deadlock", "overwatch", "heroes-of-the-storm",
        }
        self.assertEqual(set(games), expected)
        for game in expected:
            for mode in ("agent", "server"):
                for profile in ("neutral", "manacost"):
                    with self.subTest(game=game, mode=mode, profile=profile):
                        result = resolve_context(ROOT, game=game, profile=profile, execution=mode)
                        self.assertEqual(result["game"]["id"], game)
                        self.assertEqual(result["profile"]["id"], profile)
                        self.assertEqual(result["execution"], mode)
                        self.assertEqual(result["resolution_scope"], "metadata_only")
                        self.assertIsNone(result["patch"])

    def test_generic_task_does_not_inherit_hearthstone(self):
        result = resolve_context(ROOT, game=None)
        self.assertIsNone(result["game"])
        self.assertEqual(result["profile"]["id"], "neutral")

    def test_invalid_context_is_rejected_without_fallback(self):
        for overrides in (
            {"game": "unknown"}, {"game": "../hearthstone"}, {"game": []},
            {"profile": "unknown"}, {"profile": []}, {"execution": "unknown"},
            {"patch": ""}, {"patch": 123}, {"game": None, "patch": "1.0"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                resolve_context(ROOT, **({"game": "hearthstone"} | overrides))

    def test_patch_is_preserved_as_supplied_metadata(self):
        result = resolve_context(ROOT, game="world-of-warcraft", patch="user-supplied-build")
        self.assertEqual(result["patch"], "user-supplied-build")

    def test_catalog_versions_duplicates_and_fields_are_validated(self):
        baseline = json.loads((ROOT / "games/registry.json").read_text(encoding="utf-8"))
        mutations = []
        for version in (2, True, "1"):
            mutations.append(baseline | {"schema_version": version})
        mutations.append(baseline | {"games": []})
        mutations.append(baseline | {"games": [baseline["games"][0]] * 2})
        for field, value in (("id", "../bad"), ("title", " "), ("version", "01.0.0")):
            changed = copy.deepcopy(baseline)
            changed["games"][0][field] = value
            mutations.append(changed)
        changed = copy.deepcopy(baseline)
        changed["games"][0]["runtime"] = "unimplemented"
        mutations.append(changed)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "games").mkdir()
            for catalog in mutations:
                (root / "games/registry.json").write_text(json.dumps(catalog), encoding="utf-8")
                with self.subTest(catalog=catalog), self.assertRaises(ValueError):
                    load_catalog(root, "games")

    def test_catalog_hash_ignores_formatting_but_tracks_content(self):
        catalog = json.loads((ROOT / "games/registry.json").read_text(encoding="utf-8"))
        _, initial_hash = load_catalog(ROOT, "games")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "games").mkdir()
            path = root / "games/registry.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            self.assertEqual(load_catalog(root, "games")[1], initial_hash)
            catalog["games"][0]["version"] = "0.2.0"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            self.assertNotEqual(load_catalog(root, "games")[1], initial_hash)

    def test_cli_runs_from_outside_checkout_and_unknown_game_fails(self):
        script = ROOT / "tools/resolve_context.py"
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "-S", str(script), "--game", "deadlock", "--execution", "server"],
                cwd=temporary, capture_output=True, text=True, check=True,
            )
            self.assertEqual(json.loads(result.stdout)["game"]["id"], "deadlock")
            invalid = subprocess.run(
                [sys.executable, "-S", str(script), "--game", "unknown"],
                cwd=temporary, capture_output=True, text=True,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertEqual(invalid.stdout, "")


if __name__ == "__main__":
    unittest.main()

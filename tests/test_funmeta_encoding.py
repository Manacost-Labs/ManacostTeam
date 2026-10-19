import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/funmeta/scripts/funmeta.py"
sys.path.insert(0, str(SCRIPT.parent))
from deck_code import encode, decode, normalize_deck


class EncodingTests(unittest.TestCase):
    def test_independent_codec_golden_vectors(self):
        # Expected strings from manacost-deckstrings 1.0.0, not this encoder.
        cases = [({"format": 1, "heroes": [7], "cards": [[1, 2], [2, 2], [3, 2], [4, 1]], "sideboards": []},
                  "AAEBAQcBBAMBAgMAAA=="),
                 ({"format": 2, "heroes": [7], "cards": [[90749, 1], [1, 2]],
                   "sideboards": [[69616, 1, 90749], [76984, 2, 90749], [78079, 3, 90749]]},
                  "AAECAQcB/cQFAQEAAQHwnwT9xAUBuNkE/cQFAf/hBAP9xAU=")]
        for deck, expected in cases:
            with self.subTest(expected=expected):
                before = copy.deepcopy(deck)
                self.assertEqual(encode(deck), expected)
                self.assertEqual(decode(expected), normalize_deck(deck))
                self.assertEqual(deck, before)

    def test_historical_n_copy_list_and_input_order(self):
        deck = decode("AAEBAQcAAAQBAwIDAwMEAw==")
        self.assertEqual(decode(encode(deck)), deck)
        reversed_deck = copy.deepcopy(deck)
        reversed_deck["cards"].reverse()
        self.assertEqual(encode(reversed_deck), encode(deck))

    def test_rejects_duplicate_missing_owner_and_overflow(self):
        base = {"format": 2, "heroes": [7], "cards": [[1, 1]], "sideboards": []}
        for update in ({"cards": [[1, 1], [1, 2]]}, {"sideboards": [[2, 1, 3]]},
                       {"heroes": [2**31]}, {"cards": [[1, 2**31]]}, {"cards": [[True, 1]]},
                       {"cards": [[i, 1] for i in range(1, 1002)]}):
            with self.subTest(update=str(update)[:80]), self.assertRaises(ValueError):
                encode({**base, **update})

    def test_cli_never_claims_legality_or_writes_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "deck.json"
            path.write_text(json.dumps({"format": 2, "heroes": [7], "cards": [[1, 1]], "sideboards": []}))
            before = path.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPT), "encode", str(path)], capture_output=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertFalse(output["legality_verified"])
            self.assertEqual(output["origin"], "reconstructed-list")
            self.assertEqual(path.read_bytes(), before)

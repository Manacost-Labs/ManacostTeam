"""Synthetic catalog fixtures exercise transport; none prove game legality."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/funmeta/scripts/funmeta.py"
sys.path.insert(0, str(SCRIPT.parent))
from catalog import audit_captures, ingest, inspection_queue
from deck_code import encode
from discovery import plan
from funmeta import initialize


def capture(class_name="Mage", *, offset=0, limit=2, total=2, stale=False):
    return {"request": {"className": class_name, "format": "standard", "limit": limit, "offset": offset},
            "response": {"retrievedAt": "2026-10-20T10:00:00Z", "data": {
                "data": [{"id": offset+i, "class": class_name, "format": "Standard",
                          "title": f"Synthetic list {offset+i}", "url": f"https://creator.example/{class_name}/{offset+i}",
                          "deck_code": "AAECAQcCAQIAAAA=", "added_at": "2026-10-19T10:00:00Z"}
                         for i in range(min(limit, max(0, total-offset)))],
                "meta": {"count": total, "limit": limit, "offset": offset,
                         "stale": stale, "fetched_at": "2026-10-20T09:00:00Z"}}}}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.selection = initialize(self.root / "run", "2026-10-20", "standard")
        self.capture_path = self.root / "response.json"

    def import_capture(self, value):
        self.capture_path.write_text(json.dumps(value), encoding="utf-8")
        return ingest(self.selection, self.capture_path)

    def data(self):
        return json.loads(self.selection.read_text(encoding="utf-8"))

    def test_intake_preserves_raw_evidence_without_promoting_a_deck(self):
        result = self.import_capture(capture())
        data = self.data()
        self.assertEqual(result["new_leads"], 2)
        self.assertEqual(data["candidates"], [])
        self.assertEqual(len(data["gaps"]), 11)
        self.assertTrue(all(s["access"] == "excerpt" for s in data["sources"]))
        self.assertTrue(all("deck_list" not in lead and "legality" not in lead for lead in data["catalog_leads"]))
        record = data["catalog_captures"][0]
        raw = (self.selection.parent / record["snapshot"]).read_bytes()
        self.assertEqual(raw, self.capture_path.read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), record["sha256"])
        self.assertEqual(data["search_log"][0]["status"], "inspected")
        self.assertEqual(plan(data)["remaining_catalog_leads"], 1)  # Two exports, one composition.
        self.assertEqual(len(plan(data)["leads_to_inspect"][0]["source_ids"]), 2)

    def test_mcp_text_wrapper_and_exact_reimport_are_idempotent(self):
        value = capture()
        value["response"] = {"content": [{"type": "text", "text": json.dumps(value["response"])}]}
        self.import_capture(value)
        before = self.selection.read_bytes()
        snapshots = list((self.selection.parent / "sources").iterdir())
        result = ingest(self.selection, self.capture_path)
        self.assertEqual(result["status"], "already_imported")
        self.assertEqual(self.selection.read_bytes(), before)
        self.assertEqual(list((self.selection.parent / "sources").iterdir()), snapshots)

    def test_pagination_uses_real_count_and_does_not_lose_last_page(self):
        self.assertEqual(self.import_capture(capture(total=3))["next_offset"], 2)
        self.assertIsNone(self.import_capture(capture(total=3, offset=2))["next_offset"])
        data = self.data()
        self.assertEqual(len(data["catalog_leads"]), 3)
        self.assertFalse(any(t["class"] == "mage" and t["channel"] == "catalog"
                             for t in plan(data, 22)["suggested_queries"]))

    def test_empty_capture_is_evidence_of_empty_response_only(self):
        result = self.import_capture(capture(total=0))
        data = self.data()
        self.assertEqual(result["new_leads"], 0)
        self.assertEqual(data["search_log"][0]["status"], "empty")
        self.assertEqual(data["sources"], [])
        self.assertEqual(len(data["gaps"]), 11)
        audit_captures(data, self.selection.parent)
        snapshot = self.selection.parent / data["catalog_captures"][0]["snapshot"]
        snapshot.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            audit_captures(data, self.selection.parent)

    def test_invalid_capture_does_not_partially_modify_run(self):
        cases = []
        for label, mutate in (
            ("wrong_class_alias", lambda v: v["request"].update(className="Death Knight")),
            ("mixed_class", lambda v: v["response"]["data"]["data"][1].update(**{"class": "Priest"})),
            ("wrong_format", lambda v: v["request"].update(format="wild")),
            ("mixed_format", lambda v: v["response"]["data"]["data"][0].update(format="Wild")),
            ("incomplete_page", lambda v: v["response"]["data"]["data"].pop()),
            ("wrong_offset", lambda v: v["response"]["data"]["meta"].update(offset=2)),
            ("restricted_query", lambda v: v["request"].update(query="one author")),
            ("missing_stale", lambda v: v["response"]["data"]["meta"].pop("stale")),
            ("invalid_url", lambda v: v["response"]["data"]["data"][0].update(url="javascript:alert(1)")),
            ("future_capture", lambda v: v["response"].update(retrievedAt="2026-10-21T10:00:00Z")),
            ("tool_error", lambda v: v["response"].update(isError=True)),
            ("out_of_sequence", lambda v: v["request"].update(offset=1)),
        ):
            value = capture()
            mutate(value)
            cases.append((label, value))
        before = self.selection.read_bytes()
        for label, value in cases:
            with self.subTest(case=label), self.assertRaises(ValueError):
                self.import_capture(value)
            self.assertEqual(self.selection.read_bytes(), before)
            self.assertEqual(list((self.selection.parent / "sources").iterdir()), [])

    def test_out_of_sequence_or_conflicting_page_does_not_replace_evidence(self):
        with self.assertRaisesRegex(ValueError, "out of sequence"):
            self.import_capture(capture(offset=2, total=4))
        self.import_capture(capture())
        before = self.selection.read_bytes()
        changed = capture(stale=True)
        with self.assertRaisesRegex(ValueError, "already imported"):
            self.import_capture(changed)
        self.assertEqual(self.selection.read_bytes(), before)

    def test_failed_commit_rolls_back_only_owned_new_files(self):
        before = self.selection.read_bytes()
        material = self.selection.parent / "material.md"
        material_before = material.read_bytes()
        review = self.selection.parent / "review.json"
        review.write_text('{"verdict":"revise"}', encoding="utf-8")
        with patch("catalog.os.replace", side_effect=OSError("synthetic write failure")):
            with self.assertRaisesRegex(OSError, "synthetic write failure"):
                self.import_capture(capture())
        self.assertEqual(self.selection.read_bytes(), before)
        self.assertEqual(material.read_bytes(), material_before)
        self.assertEqual(review.read_text(encoding="utf-8"), '{"verdict":"revise"}')
        self.assertEqual(list((self.selection.parent / "sources").iterdir()), [])
        self.assertEqual({p.name for p in self.selection.parent.iterdir()}, {"selection.json", "material.md", "sources", "review.json"})

    def test_existing_snapshot_is_never_overwritten_or_deleted(self):
        value = capture()
        self.capture_path.write_text(json.dumps(value), encoding="utf-8")
        digest = hashlib.sha256(self.capture_path.read_bytes()).hexdigest()
        snapshot = self.selection.parent / f"sources/catalog-{digest}.json"
        snapshot.write_text("preserved", encoding="utf-8")
        before = self.selection.read_bytes()
        with self.assertRaises(FileExistsError):
            ingest(self.selection, self.capture_path)
        self.assertEqual(snapshot.read_text(encoding="utf-8"), "preserved")
        self.assertEqual(self.selection.read_bytes(), before)

    def test_concurrent_edit_is_preserved_and_owned_snapshot_is_removed(self):
        self.capture_path.write_text(json.dumps(capture()), encoding="utf-8")
        original_reader = Path.read_bytes
        concurrent = self.selection.read_bytes() + b"\n"
        reads = 0
        def read_bytes(path):
            nonlocal reads
            if path == self.selection:
                reads += 1
                if reads == 2:
                    path.write_bytes(concurrent)
            return original_reader(path)
        with patch.object(Path, "read_bytes", read_bytes):
            with self.assertRaisesRegex(ValueError, "changed during import"):
                ingest(self.selection, self.capture_path)
        self.assertEqual(self.selection.read_bytes(), concurrent)
        self.assertEqual(list((self.selection.parent / "sources").iterdir()), [])

    def test_tampered_capture_is_not_silently_accepted_on_reimport(self):
        self.import_capture(capture(total=0))
        data = self.data()
        (self.selection.parent / data["catalog_captures"][0]["snapshot"]).write_bytes(b"changed")
        before = self.selection.read_bytes()
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            ingest(self.selection, self.capture_path)
        self.assertEqual(self.selection.read_bytes(), before)

    def test_queue_groups_cosmetic_heroes_and_preserves_other_compositions(self):
        value = capture(limit=3, total=3)
        rows = value["response"]["data"]["data"]
        rows[1]["deck_code"] = encode({"format": 2, "heroes": [99], "cards": [[1, 1], [2, 1]], "sideboards": []})
        rows[2]["deck_code"] = encode({"format": 2, "heroes": [7], "cards": [[3, 2]], "sideboards": []})
        self.import_capture(value)
        queue = inspection_queue(self.data(), 6)
        self.assertEqual(queue["remaining_catalog_leads"], 2)
        self.assertEqual([len(t["source_ids"]) for t in queue["leads_to_inspect"]], [2, 1])

    def test_stale_missing_invalid_codes_and_future_dates_are_visible(self):
        value = capture(total=3, limit=3, stale=True)
        rows = value["response"]["data"]["data"]
        rows[0]["deck_code"] = None
        rows[1]["deck_code"] = "invalid code"
        rows[2]["published_at"] = "2026-10-21T12:00:00Z"
        self.import_capture(value)
        queue = plan(self.data())
        self.assertEqual(queue["remaining_catalog_leads"], 2)
        self.assertEqual(queue["deferred_catalog_lead_count"], 1)
        warnings = [t["warnings"] for t in queue["leads_to_inspect"]]
        self.assertTrue(all("stale_or_unknown_catalog" in w for w in warnings))
        self.assertIn("missing_code", warnings[0])
        self.assertIn("invalid_or_wrong_format_code", warnings[1])

    def test_queue_rotates_classes_and_does_not_repeat_an_existing_candidate(self):
        self.import_capture(capture(total=3, limit=3))
        self.import_capture(capture("Priest"))
        data = self.data()
        queue = inspection_queue(data, 2)
        self.assertEqual({t["class"] for t in queue["leads_to_inspect"]}, {"mage", "priest"})
        data["candidates"] = [{"id": "handled", "class": "mage", "decision": "reject",
                               "deck_list": {"format": 2, "heroes": [7], "cards": [[1, 1], [2, 1]], "sideboards": []}}]
        self.assertEqual([t["class"] for t in inspection_queue(data, 6)["leads_to_inspect"]], ["priest"])

    def test_pending_source_suppresses_equivalent_exports_without_inventing_a_list(self):
        self.import_capture(capture())
        data = self.data()
        data["candidates"] = [{"id": "pending", "class": "mage", "decision": "pending",
                               "source_ids": [data["catalog_leads"][0]["source_id"]]}]
        result = plan(data)
        self.assertEqual(result["remaining_catalog_leads"], 0)
        self.assertIn("transcribe_independent_list", result["candidate_tasks"][0]["tasks"])
        self.assertNotIn("deck_list", data["candidates"][0])

    def test_fresh_alternative_is_preferred_but_stale_source_is_preserved(self):
        self.import_capture(capture(limit=1, total=2, stale=True))
        self.import_capture(capture(limit=1, total=2, offset=1))
        result = inspection_queue(self.data(), 6)
        self.assertEqual(result["remaining_catalog_leads"], 1)
        group = result["leads_to_inspect"][0]
        self.assertTrue(group["url"].endswith("/1"))
        self.assertEqual(len(group["source_ids"]), 2)
        self.assertNotIn("stale_or_unknown_catalog", group["warnings"])

    def test_cli_catalog_import_preserves_material_and_does_not_create_review(self):
        self.capture_path.write_text(json.dumps(capture()), encoding="utf-8")
        material = self.selection.parent / "material.md"
        before = material.read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), "catalog", str(self.selection), str(self.capture_path)],
                                capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "catalog_imported")
        self.assertEqual(material.read_bytes(), before)
        self.assertFalse((self.selection.parent / "review.json").exists())
        # Saved captures remain external data, not an instruction channel.
        self.assertEqual(self.data()["candidates"], [])

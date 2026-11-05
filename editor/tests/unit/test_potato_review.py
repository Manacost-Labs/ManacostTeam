"""Synthetic round trips for the optional, local Potato review interface."""

import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))
import potato_review as potato


class PotatoReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="manacost-potato-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pairs = self.root / "pairs.json"
        self.criteria = ["learned_new", "no_skip", "decisions", "author_voice"]
        self.rows = [
            {
                "id": "synthetic-case",
                "source": "Черновик <script>alert(1)</script>",
                "A": "Первый текст",
                "B": "Второй текст",
                "criteria": self.criteria,
            },
            {
                "id": "pending-case",
                "source": "Черновик",
                "A": "А",
                "B": "Б",
                "criteria": self.criteria,
            },
        ]
        self.pairs.write_text(json.dumps(self.rows), encoding="utf-8")
        self.key = self.root / "key.json"
        self.key.write_text(
            json.dumps(
                {
                    "protocol": "pairs",
                    "criteria": self.criteria,
                    "run": {
                        "editor": "offline",
                        "synthetic_ids": ["synthetic-case", "pending-case"],
                    },
                    "pairs": [{"id": row["id"], "A": "ai", "B": "human"} for row in self.rows],
                }
            ),
            encoding="utf-8",
        )
        self.project = self.root / "project"

    def state(self, *, origin=None, attested=True):
        labels = {"preference": {"selection": "A"}, "evidence": {"text_box": "В A яснее условие."}}
        if attested:
            labels["attestation"] = {potato.ATTESTATION: "true"}
        for side in ("A", "B"):
            for criterion in self.criteria:
                labels[f"{side}__{criterion}"] = {"4": "4"}
        state = {
            "user_id": "Synthetic test reviewer",
            "origin": origin or {"kind": "human"},
            "instance_id_to_label_to_value": {"synthetic-case": labels},
        }
        user = self.project / "annotations" / "reviewer"
        user.mkdir(parents=True)
        (user / "user_state.json").write_text(json.dumps(state), encoding="utf-8")
        history = {
            "user_id": state["user_id"],
            "instance_id": "synthetic-case",
            "timestamp": "2026-11-05T12:34:56.123456",
            "action_type": "add_label",
            "schema_name": "attestation",
            "label_name": potato.ATTESTATION,
            "new_value": "true",
        }
        (user / "annotation_history.jsonl").write_text(json.dumps(history) + "\n", encoding="utf-8")
        return user, state

    def test_export_is_blind_frozen_and_has_no_ai_assistance(self):
        potato.export_project(self.pairs, self.project)
        config = json.loads((self.project / "config.yaml").read_text())
        dataset = (self.project / "data.jsonl").read_text()
        self.assertNotIn("key.json", "".join(p.read_text() for p in self.project.iterdir()))
        self.assertNotIn("<script>", dataset)
        self.assertIn("&lt;script&gt;", dataset)
        self.assertEqual(config["ai_support"], {"enabled": False})
        schemes = {row["name"] for row in config["annotation_schemes"]}
        self.assertIn("A__decisions", schemes)
        self.assertIn("B__author_voice", schemes)
        with self.assertRaises(FileExistsError):
            potato.export_project(self.pairs, self.project)

    def test_real_potato_state_shape_roundtrips_to_existing_blind_report(self):
        potato.export_project(self.pairs, self.project)
        user, state = self.state()
        state["origin"] = {}  # Actual default saved by Potato 2.14.
        # Potato 2.14 persists [{schema, name}, value] label entries.
        state["instance_id_to_label_to_value"]["synthetic-case"] = [
            [{"schema": schema, "name": label}, value]
            for schema, labels in state["instance_id_to_label_to_value"]["synthetic-case"].items()
            for label, value in labels.items()
        ]
        (user / "user_state.json").write_text(json.dumps(state), encoding="utf-8")
        out = self.root / "human"
        potato.import_project(self.project, self.pairs, self.key, out)
        ratings = json.loads((out / "ratings.json").read_text())
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(ratings[0]["reviewer"], "Synthetic test reviewer")
        self.assertEqual(ratings[0]["reviewed_at"], "2026-11-05T12:34:56.123456+00:00")
        self.assertEqual(report["human_attested_ratings"], 1)
        self.assertFalse(report["metric"]["human"]["measured"])
        self.assertFalse(report["quality_improvement_confirmed"])
        self.assertEqual(report["preferences"], {"ai": 1})
        self.assertEqual(report["pending"], ["pending-case"])
        with self.assertRaises(FileExistsError):
            potato.import_project(self.project, self.pairs, self.key, out)

    def test_pending_and_machine_records_cannot_become_human_results(self):
        potato.export_project(self.pairs, self.project)
        user, state = self.state(attested=False)
        potato.import_project(self.project, self.pairs, self.key, self.root / "pending")
        self.assertEqual(json.loads((self.root / "pending/report.json").read_text())["rated"], 0)
        state["origin"] = {"kind": "llm", "model": "test"}
        (user / "user_state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "human"):
            potato.import_project(self.project, self.pairs, self.key, self.root / "machine")
        self.assertFalse((self.root / "machine").exists())

    def test_drift_and_missing_history_fail_before_writes(self):
        potato.export_project(self.pairs, self.project)
        user, state = self.state()
        history = user / "annotation_history.jsonl"
        history.unlink()
        with self.assertRaisesRegex(ValueError, "history"):
            potato.import_project(self.project, self.pairs, self.key, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())
        (self.project / "data.jsonl").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            potato.import_project(self.project, self.pairs, self.key, self.root / "bad")

    def test_unknown_ids_duplicate_users_and_invalid_scores_are_rejected(self):
        potato.export_project(self.pairs, self.project)
        user, state = self.state()
        labels = state["instance_id_to_label_to_value"]
        labels["unknown"] = labels.pop("synthetic-case")
        (user / "user_state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unknown"):
            potato.import_project(self.project, self.pairs, self.key, self.root / "bad")
        labels["synthetic-case"] = labels.pop("unknown")
        labels["synthetic-case"]["A__decisions"] = {"6": "6"}
        (user / "user_state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "score"):
            potato.import_project(self.project, self.pairs, self.key, self.root / "bad")
        labels["synthetic-case"]["A__decisions"] = {"4": "4"}
        (user / "user_state.json").write_text(json.dumps(state), encoding="utf-8")
        shutil.copytree(user, user.with_name("duplicate"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            potato.import_project(self.project, self.pairs, self.key, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_another_blind_key_with_same_ids_cannot_swap_the_results(self):
        potato.export_project(self.pairs, self.project)
        self.state()
        key = json.loads(self.key.read_text())
        for row in key["pairs"]:
            row["A"], row["B"] = row["B"], row["A"]
        self.key.write_text(json.dumps(key))
        with self.assertRaisesRegex(ValueError, "blind key"):
            potato.import_project(self.project, self.pairs, self.key, self.root / "wrong-key")
        self.assertFalse((self.root / "wrong-key").exists())

    def test_malformed_states_fail_cleanly_without_creating_a_report(self):
        potato.export_project(self.pairs, self.project)
        user, state = self.state()
        for malformed in [
            None,
            [],
            {**state, "instance_id_to_label_to_value": None},
            {**state, "instance_id_to_label_to_value": {"synthetic-case": [None]}},
            {**state, "instance_id_to_label_to_value": {"synthetic-case": {"preference": []}}},
        ]:
            with self.subTest(malformed=malformed):
                (user / "user_state.json").write_text(json.dumps(malformed))
                with self.assertRaises(ValueError):
                    potato.import_project(self.project, self.pairs, self.key, self.root / "bad")
                self.assertFalse((self.root / "bad").exists())

    def test_history_is_reconciled_by_time_not_file_order(self):
        potato.export_project(self.pairs, self.project)
        user, _ = self.state()
        history = user / "annotation_history.jsonl"
        added = json.loads(history.read_text())
        deleted = {
            **added,
            "timestamp": "2026-11-05T13:00:00",
            "action_type": "delete_label",
            "new_value": None,
        }
        history.write_text(json.dumps(deleted) + "\n" + json.dumps(added) + "\n")
        with self.assertRaisesRegex(ValueError, "removed"):
            potato.import_project(self.project, self.pairs, self.key, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_multiple_human_reviewers_keep_distinct_observations(self):
        potato.export_project(self.pairs, self.project)
        user, state = self.state()
        other = user.with_name("other-reviewer")
        shutil.copytree(user, other)
        state["user_id"] = "Second synthetic reviewer"
        (other / "user_state.json").write_text(json.dumps(state))
        history = other / "annotation_history.jsonl"
        record = json.loads(history.read_text())
        record["user_id"] = state["user_id"]
        history.write_text(json.dumps(record) + "\n")
        result = potato.import_project(self.project, self.pairs, self.key, self.root / "multi")
        self.assertEqual(result, {"reviewed": 2, "pending": 1})
        report = json.loads((self.root / "multi/report.json").read_text())
        self.assertEqual(report["human_attested_ratings"], 2)
        self.assertEqual(len(report["observations"]), 2)

    @unittest.skipUnless(
        importlib.util.find_spec("potato"), "optional pinned Potato runtime not installed"
    )
    def test_live_pinned_potato_http_state_import(self):
        import requests
        from bs4 import BeautifulSoup

        potato.export_project(self.pairs, self.project)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with (self.root / "server.log").open("w") as log:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(potato.__file__)),
                    "serve",
                    "--project",
                    str(self.project),
                    "--port",
                    str(port),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                session = requests.Session()
                deadline = time.monotonic() + 45
                while True:
                    try:
                        response = session.get(base, timeout=1)
                        response.raise_for_status()
                        break
                    except requests.RequestException:
                        if proc.poll() is not None or time.monotonic() >= deadline:
                            self.fail((self.root / "server.log").read_text()[-2500:])
                        time.sleep(0.1)
                credentials = {
                    "email": "Synthetic HTTP reviewer",
                    "pass": "local-synthetic-test-only",
                }
                session.post(base + "/register", data=credentials, timeout=5).raise_for_status()
                response = session.post(base + "/auth", data=credentials, timeout=5)
                response.raise_for_status()
                page = BeautifulSoup(response.text, "html.parser")
                self.assertEqual(page.find(id="instance_id")["value"], "synthetic-case")
                self.assertIsNone(page.find("script", string=lambda text: text == "alert(1)"))
                values = {
                    "preference:selection": "A",
                    "evidence:text_box": "Синтетическая проверка.",
                    f"attestation:{potato.ATTESTATION}": potato.ATTESTATION,
                }
                for side in ("A", "B"):
                    for criterion in self.criteria:
                        values[f"{side}__{criterion}:4"] = "4"
                saved = session.post(
                    base + "/updateinstance",
                    json={"instance_id": "synthetic-case", "annotations": values},
                    headers={"Origin": base},
                    timeout=5,
                )
                saved.raise_for_status()
                self.assertEqual(saved.json()["status"], "success")
                potato.import_project(self.project, self.pairs, self.key, self.root / "live-report")
                report = json.loads((self.root / "live-report/report.json").read_text())
                self.assertEqual(report["rated"], 1)
                self.assertEqual(report["pending"], ["pending-case"])
                self.assertFalse(report["metric"]["human"]["measured"])
            finally:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()

"""Offline checks; the developer's Atlas credentials are never used."""

# Import server first so its eventlet monkey patch precedes all other imports.
import server

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pymongo.errors import DuplicateKeyError, OperationFailure
from werkzeug.middleware.proxy_fix import ProxyFix

import database
import question_loader
from game_state import GameRegistry


PACK = json.loads((question_loader.QUESTIONS_DIR / "classic.json").read_text(encoding="utf-8"))


class MongoStorageTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"QUESTION_STORAGE": "mongodb", "MONGODB_URI": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.collection = MagicMock()
        self.connection = patch.object(question_loader, "get_question_collection", return_value=self.collection)
        self.connection.start()
        self.addCleanup(self.connection.stop)
        question_loader._mongo_collection.cache_clear()
        self.addCleanup(question_loader._mongo_collection.cache_clear)

    def test_import_only_inserts_missing_packs_and_repeats_safely(self):
        question_loader.list_sets()
        expected = len(list(question_loader.QUESTIONS_DIR.glob("*.json")))
        self.assertEqual(self.collection.update_one.call_count, expected)
        for call in self.collection.update_one.call_args_list:
            self.assertTrue(call.kwargs["upsert"])
            self.assertEqual(set(call.args[1]), {"$setOnInsert"})
        question_loader.list_sets()
        self.assertEqual(self.collection.update_one.call_count, expected)
        question_loader._mongo_collection.cache_clear()
        question_loader.list_sets()
        self.assertEqual(self.collection.update_one.call_count, expected * 2)

    def test_duplicate_name_is_retried_without_writing_files(self):
        self.collection.insert_one.side_effect = [DuplicateKeyError("duplicate"), None]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(question_loader, "QUESTIONS_DIR", Path(directory)):
                stem, name = question_loader.save_set("Same Name", PACK["categories"], PACK["questions"])
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual((stem, name), ("same-name-2", "Same Name"))
        self.assertEqual(self.collection.insert_one.call_args.args[0]["_id"], stem)

    def test_load_uses_database_and_maps_category_numbers(self):
        self.collection.find_one.return_value = PACK
        bundle = question_loader.load_set("mongo-only")
        self.collection.find_one.assert_called_once_with({"_id": "mongo-only"})
        self.assertEqual(sum(map(len, bundle["questions_by_category"].values())), 36)
        self.assertEqual(bundle["categories"], PACK["categories"])

    def test_missing_set(self):
        self.collection.find_one.return_value = None
        with self.assertRaises(FileNotFoundError):
            question_loader.load_set("not-found")

    def test_listing_returns_metadata_without_answers(self):
        self.collection.aggregate.return_value = [{"_id": "pack", "name": "Pack",
                                                   "categories": PACK["categories"], "question_count": 36}]
        result = question_loader.list_sets()
        self.assertEqual(result[0]["question_count"], 36)
        self.assertNotIn("questions", result[0])
        self.assertNotIn("answer", json.dumps(result))

    def test_database_outage_returns_safe_503_and_does_not_save_to_disk(self):
        self.collection.update_one.side_effect = OperationFailure("private-password-and-uri")
        client = server.app.test_client()
        with patch.object(question_loader, "save_set", wraps=question_loader.save_set):
            responses = [
                client.get("/api/question-sets"),
                client.get("/healthz"),
                client.post("/api/question-sets", json={**PACK, "name": "Outage Test"}),
                client.post("/api/create", json={"question_set": "classic", "teams": ["A"]}),
            ]
        for response in responses:
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private-password", response.get_data(as_text=True))
        self.collection.insert_one.assert_not_called()

    def test_required_mongodb_without_uri_never_falls_back(self):
        database.get_question_collection.cache_clear()
        with self.assertRaises(database.StorageUnavailable):
            database.get_question_collection()

    def test_health_identifies_mongodb_backend(self):
        response = server.app.test_client().get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["question_storage"], "mongodb")


class GameAndNetworkTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"QUESTION_STORAGE": "json"})
        environment.start()
        self.addCleanup(environment.stop)
        registry = patch.object(server, "registry", GameRegistry())
        registry.start()
        self.addCleanup(registry.stop)
        self.old_url = server.app.config.get("PUBLIC_URL", "")
        server.app.config["PUBLIC_URL"] = ""
        self.addCleanup(server.app.config.__setitem__, "PUBLIC_URL", self.old_url)
        self.client = server.app.test_client()
        response = self.client.post("/api/create", json={"question_set": "classic", "teams": ["A"]})
        self.assertEqual(response.status_code, 200)
        self.game = response.get_json()

    def test_json_path_traversal_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            question_loader.load_set("../../DB_info")

    def test_health_identifies_json_backend(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["question_storage"], "json")

    def test_public_url_used_for_host_link_and_qr(self):
        server.app.config["PUBLIC_URL"] = "https://game.example"
        code = self.game["code"]
        response = self.client.get(f"/host/{code}")
        self.assertIn("https://game.example", response.get_data(as_text=True))
        with patch.object(server.qrcode, "make") as make:
            self.assertEqual(self.client.get(f"/host/{code}/qr.png").status_code, 200)
            make.assert_called_once_with(f"https://game.example/join?code={code}")

    def test_proxy_https_is_used_in_qr_when_no_explicit_url(self):
        with patch.object(server.app, "wsgi_app", ProxyFix(server.app.wsgi_app, x_proto=1)):
            with patch.object(server.qrcode, "make") as make:
                self.client.get(f"/host/{self.game['code']}/qr.png", base_url="http://game.example",
                                headers={"X-Forwarded-Proto": "https"})
                make.assert_called_once_with(f"https://game.example/join?code={self.game['code']}")

    def test_host_and_phone_can_play_with_loaded_pack(self):
        host = server.socketio.test_client(server.app)
        player = server.socketio.test_client(server.app)
        self.addCleanup(host.disconnect)
        self.addCleanup(player.disconnect)
        code = self.game["code"]
        host.emit("host:join", {"code": code, "host_token": self.game["host_token"]})
        player.emit("player:join", {"code": code, "name": "Player", "team": "A"})
        host.emit("host:start_game", {"code": code})
        room = server.registry.get(code)
        category = room.categories[0]
        points = room.questions[category][0]["points"]
        host.emit("host:pick_question", {"code": code, "category": category, "points": points})
        player_states = [event["args"][0] for event in player.get_received() if event["name"] == "state"]
        self.assertNotIn("answer", player_states[-1]["current"])
        player.emit("player:buzz", {"code": code})
        self.assertEqual(room.phase, "buzzed")
        host.emit("host:reveal_answer", {"code": code})
        host.emit("host:judge", {"code": code, "correct": True})
        self.assertEqual(room.teams[0]["score"], points)
        self.assertEqual(room.phase, "board")

    def test_bad_payloads_get_validation_errors(self):
        for endpoint, payload in [("/api/create", [1]), ("/api/question-sets", {"name": 3}),
                                  ("/api/create", {"question_set": "classic", "teams": [3]}),
                                  ("/api/create", {"question_set": "classic", "teams": ["A"],
                                                   "question_time": "bad"})]:
            self.assertEqual(self.client.post(endpoint, json=payload).status_code, 400)


if __name__ == "__main__":
    unittest.main()

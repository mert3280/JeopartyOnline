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
        self.collection.find_one.assert_called_once_with({"_id": "mongo-only", "deleted": {"$ne": True}})
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
                client.post("/api/question-sets", json={**PACK, "name": "Outage Test", "password": "pw"}),
                client.post("/api/create", json={"question_set": "classic", "teams": ["A"]}),
            ]
        for response in responses:
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private-password", response.get_data(as_text=True))
        self.collection.insert_one.assert_not_called()

    def test_deleting_bundled_pack_leaves_tombstone_so_it_is_not_reimported(self):
        self.collection.find_one.return_value = PACK
        question_loader.delete_set("classic")
        self.collection.replace_one.assert_called_once_with({"_id": "classic"}, {"deleted": True})
        self.collection.delete_one.assert_not_called()

    def test_deleting_user_set_removes_document(self):
        self.collection.find_one.return_value = PACK
        question_loader.delete_set("my-own-set")
        self.collection.delete_one.assert_called_once_with({"_id": "my-own-set"})

    def test_listing_skips_deleted_sets(self):
        self.collection.aggregate.return_value = []
        question_loader.list_sets()
        pipeline = self.collection.aggregate.call_args.args[0]
        self.assertEqual(pipeline[0], {"$match": {"deleted": {"$ne": True}}})

    def test_required_mongodb_without_uri_never_falls_back(self):
        database.get_question_collection.cache_clear()
        with self.assertRaises(database.StorageUnavailable):
            database.get_question_collection()

    def test_health_identifies_mongodb_backend(self):
        response = server.app.test_client().get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["question_storage"], "mongodb")


class QuestionSetEditingTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"QUESTION_STORAGE": "json", "MASTER_PASSWORD": "s3cret;/.",
                                              "DELETE_PASSWORD": ""})
        environment.start()
        self.addCleanup(environment.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        questions_dir = patch.object(question_loader, "QUESTIONS_DIR", self.dir)
        questions_dir.start()
        self.addCleanup(questions_dir.stop)
        self.client = server.app.test_client()
        response = self.client.post("/api/question-sets", json={**PACK, "name": "Editable", "password": "creator"})
        self.assertEqual(response.status_code, 201)
        self.url = f"/api/question-sets/{response.get_json()['filename']}"

    def add_set(self, name, password="other"):
        response = self.client.post("/api/question-sets", json={**PACK, "name": name, "password": password})
        return f"/api/question-sets/{response.get_json()['filename']}"

    def test_get_returns_full_set_for_editor(self):
        data = self.client.get(self.url).get_json()
        self.assertEqual(data["name"], "Editable")
        self.assertEqual(len(data["questions"]), 36)

    def test_rename_keeps_contents_and_filename(self):
        response = self.client.patch(self.url, json={"name": "  Renamed  ", "password": "creator"})
        self.assertEqual(response.get_json(), {"filename": "editable", "name": "Renamed"})
        data = self.client.get(self.url).get_json()
        self.assertEqual(data["name"], "Renamed")
        self.assertEqual(len(data["questions"]), 36)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["editable.json"])

    def test_update_replaces_contents(self):
        questions = [dict(q) for q in PACK["questions"]]
        questions[0]["answer"] = "new answer"
        response = self.client.put(self.url, json={**PACK, "name": "Edited", "questions": questions,
                                                   "password": "creator"})
        self.assertEqual(response.status_code, 200)
        data = self.client.get(self.url).get_json()
        self.assertEqual(data["name"], "Edited")
        self.assertEqual(data["questions"][0]["answer"], "new answer")

    def test_update_is_validated(self):
        response = self.client.put(self.url, json={**PACK, "questions": PACK["questions"][:5],
                                                   "password": "creator"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.patch(self.url, json={"name": " ", "password": "creator"}).status_code, 400)

    def test_new_sets_need_a_creator_password(self):
        for password in (None, "", "   ", 5, "x" * 101):
            response = self.client.post("/api/question-sets", json={**PACK, "name": "N", "password": password})
            self.assertEqual(response.status_code, 400)

    def test_creator_or_master_password_can_modify(self):
        for password in ("creator", "s3cret;/."):
            self.assertEqual(self.client.post(f"{self.url}/auth", json={"password": password}).status_code, 204)
            self.assertEqual(self.client.patch(self.url, json={"name": "R", "password": password}).status_code, 200)
            self.assertEqual(self.client.put(self.url, json={**PACK, "password": password}).status_code, 200)

    def test_other_passwords_cannot_modify(self):
        self.add_set("Someone Else", password="other")
        for password in (None, "", "other", "Creator", "creator "):
            body = {**PACK, "password": password}
            self.assertEqual(self.client.post(f"{self.url}/auth", json=body).status_code, 403)
            self.assertEqual(self.client.put(self.url, json=body).status_code, 403)
            self.assertEqual(self.client.patch(self.url, json=body).status_code, 403)
            self.assertEqual(self.client.delete(self.url, json=body).status_code, 403)
        self.assertEqual(self.client.get(self.url).get_json()["name"], "Editable")

    def test_password_is_stored_in_set_file_but_never_sent_out(self):
        stored = json.loads((self.dir / "editable.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["password"], "creator")
        for path in (self.url, "/api/question-sets", "/question-sets/editable/download"):
            self.assertNotIn("creator", self.client.get(path).get_data(as_text=True))

    def test_editing_keeps_or_changes_creator_password(self):
        self.client.put(self.url, json={**PACK, "name": "Kept", "password": "creator"})
        self.assertEqual(question_loader.get_set_password("editable"), "creator")
        self.client.put(self.url, json={**PACK, "password": "creator", "new_password": "fresh"})
        self.assertEqual(self.client.post(f"{self.url}/auth", json={"password": "creator"}).status_code, 403)
        self.assertEqual(self.client.post(f"{self.url}/auth", json={"password": "fresh"}).status_code, 204)

    def test_set_without_creator_password_needs_master(self):
        (self.dir / "legacy.json").write_text(json.dumps({**PACK, "name": "Legacy"}), encoding="utf-8")
        url = "/api/question-sets/legacy"
        self.assertEqual(self.client.delete(url, json={"password": ""}).status_code, 403)
        self.assertEqual(self.client.delete(url, json={"password": "s3cret;/."}).status_code, 204)

    def test_delete_password_is_accepted_as_master_fallback(self):
        with patch.dict(os.environ, {"MASTER_PASSWORD": "", "DELETE_PASSWORD": "old-name"}):
            self.assertEqual(self.client.post(f"{self.url}/auth", json={"password": "old-name"}).status_code, 204)

    def test_delete_removes_set_with_password(self):
        self.assertEqual(self.client.delete(self.url, json={"password": "s3cret;/."}).status_code, 204)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get("/api/question-sets").get_json(), [])

    def test_delete_rejects_wrong_or_missing_password(self):
        for body in (None, {}, {"password": ""}, {"password": "wrong"}, {"password": 123}, ["s3cret;/."]):
            self.assertEqual(self.client.delete(self.url, json=body).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_without_master_only_creator_password_works(self):
        with patch.dict(os.environ, {"MASTER_PASSWORD": ""}):
            self.assertEqual(self.client.delete(self.url, json={"password": ""}).status_code, 403)
            self.assertEqual(self.client.delete(self.url, json={"password": "creator"}).status_code, 204)

    def test_template_download_can_be_uploaded_as_is(self):
        response = self.client.get("/question-sets/template.json")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        template = json.loads(response.get_data(as_text=True))
        self.assertEqual(len(template["questions"]), 36)
        self.assertEqual(self.client.post("/api/question-sets", json=template).status_code, 400)
        template["password"] = "mine"
        self.assertEqual(self.client.post("/api/question-sets", json=template).status_code, 201)

    def test_set_download_round_trips(self):
        response = self.client.get("/question-sets/editable/download")
        self.assertIn('filename="editable.json"', response.headers["Content-Disposition"])
        exported = json.loads(response.get_data(as_text=True))
        self.assertEqual(exported["name"], "Editable")
        self.assertEqual(exported["password"], "")
        exported["password"] = "copy"
        self.assertEqual(self.client.post("/api/question-sets", json=exported).get_json()["filename"],
                         "editable-2")
        self.assertEqual(self.client.get("/question-sets/nope/download").status_code, 404)

    def test_missing_or_unsafe_set_is_404(self):
        body = {**PACK, "name": "X", "password": "s3cret;/."}
        for method in ("get", "put", "patch", "delete"):
            response = getattr(self.client, method)("/api/question-sets/nope", json=body)
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.delete("/api/question-sets/..%2Fserver", json=body).status_code, 404)

    def test_pages_render(self):
        self.assertEqual(self.client.get("/question-sets").status_code, 200)
        self.assertIn('data-set-id=""', self.client.get("/question-sets/new").get_data(as_text=True))
        self.assertIn('data-set-id="editable"',
                      self.client.get("/question-sets/editable/edit").get_data(as_text=True))
        self.assertEqual(self.client.get("/make-questions").status_code, 302)


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

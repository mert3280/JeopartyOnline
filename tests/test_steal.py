"""Steal scoring, private judge pairing, and socket authorization checks."""
import server  # eventlet must patch before other imports

import os
import unittest
from unittest.mock import patch

from game_state import GameRegistry


class StealTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"QUESTION_STORAGE": "json"})
        environment.start()
        self.addCleanup(environment.stop)
        registry = patch.object(server, "registry", GameRegistry())
        registry.start()
        self.addCleanup(registry.stop)
        # Capture timeout jobs so tests can execute them deterministically.
        self.jobs = []
        tasks = patch.object(server.socketio, "start_background_task", side_effect=lambda job: self.jobs.append(job))
        tasks.start()
        self.addCleanup(tasks.stop)
        self.http = server.app.test_client()
        self.create()

    def client(self):
        client = server.socketio.test_client(server.app)
        self.addCleanup(lambda: client.disconnect() if client.is_connected() else None)
        return client

    def create(self, **settings):
        response = self.http.post("/api/create", json={
            "question_set": "classic", "game_mode": "steal", "teams": ["A", "B", "C", "D"], **settings,
        })
        self.assertEqual(response.status_code, 200)
        game = response.get_json()
        self.code = game["code"]
        self.room = server.registry.get(self.code)
        self.board = self.client()
        self.board.emit("host:join", {"code": self.code, "host_token": game["host_token"]})
        self.players = []
        for team in ("A", "B", "C", "D"):
            player = self.client()
            player.emit("player:join", {"code": self.code, "name": team, "team": team})
            self.players.append(player)
        self.judge = self.client()

    def pair(self, judge=None):
        judge = judge or self.judge
        judge.emit("judge:join", {"code": self.code})
        messages = judge.get_received()
        pairing = next(event["args"][0]["pairing_code"] for event in messages if event["name"] == "judge:pending")
        self.board.emit("host:approve_judge", {"code": self.code, "pairing_code": pairing})
        return next(event["args"][0]["judge_token"] for event in judge.get_received() if event["name"] == "judge:approved")

    def pick(self, points=100):
        self.board.emit("host:start_game", {"code": self.code})
        self.board.emit("host:pick_question", {
            "code": self.code, "category": self.room.categories[0], "points": points,
        })
        self.assertEqual(self.room.phase, "question")

    def buzz(self, index):
        self.players[index].emit("player:buzz", {"code": self.code})

    def judge_answer(self, correct):
        self.judge.emit("host:judge", {"code": self.code, "correct": correct})

    def test_default_values_and_both_screens_required(self):
        self.assertEqual((self.room.steal_decrease, self.room.steal_opportunities), (25, 2))
        self.board.emit("host:start_game", {"code": self.code})
        self.assertEqual(self.room.phase, "lobby")
        self.judge.emit("judge:join", {"code": self.code})
        self.board.emit("host:start_game", {"code": self.code})
        self.assertEqual(self.room.phase, "lobby")  # pending is not connected
        self.pair()
        self.pick()

    def test_first_second_and_third_attempt_values(self):
        for attempt, expected in enumerate((100, 75, 50)):
            with self.subTest(attempt=attempt):
                if attempt:
                    self.create()
                self.pair()
                self.pick()
                for previous in range(attempt):
                    self.buzz(previous)
                    self.judge_answer(False)
                    self.assertEqual(self.room.teams[previous]["score"], 0)
                self.assertEqual(self.room.available_points(), expected)
                self.buzz(attempt)
                self.judge_answer(True)
                self.assertEqual(self.room.teams[attempt]["score"], expected)
                self.assertEqual(self.room.phase, "board")
                self.assertIsNone(self.room.current)

    def test_teammates_and_reconnected_players_cannot_retry(self):
        self.pair()
        teammate = self.client()
        teammate.emit("player:join", {"code": self.code, "name": "A2", "team": "A"})
        player_id = next(pid for pid, p in self.room.players.items() if p["name"] == "A")
        self.pick()
        self.buzz(0)
        self.buzz(1)  # first buzz wins
        self.assertEqual(self.room.current["buzzed_team"], "A")
        self.judge_answer(False)
        self.buzz(0)
        teammate.emit("player:buzz", {"code": self.code})
        rejoined = self.client()
        rejoined.emit("player:reconnect", {"code": self.code, "player_id": player_id})
        rejoined.emit("player:buzz", {"code": self.code})
        self.assertEqual(self.room.phase, "question")
        self.assertEqual(self.room.current["attempted_teams"], ["A"])
        self.buzz(1)
        self.assertEqual(self.room.current["buzzed_team"], "B")

    def test_opportunities_exhaust_without_penalty(self):
        self.pair()
        self.pick()
        for i in range(3):
            self.buzz(i)
            self.judge_answer(False)
        self.assertEqual(self.room.phase, "board")
        self.assertTrue(self.room.asked)
        self.assertEqual([team["score"] for team in self.room.teams], [0, 0, 0, 0])
        self.buzz(3)
        self.assertEqual(self.room.phase, "board")

    def test_finish_when_no_eligible_teams_remain(self):
        self.pair()
        self.room.steal_opportunities = 14
        self.pick()
        for i in range(4):
            self.buzz(i)
            self.judge_answer(False)
        self.assertEqual(self.room.phase, "board")

    def test_custom_decrease_uses_original_points_and_floors_at_zero(self):
        self.room.steal_decrease = 60
        self.pair()
        self.pick(300)
        self.buzz(0)
        self.judge_answer(False)
        self.assertEqual(self.room.available_points(), 120)
        self.buzz(1)
        self.judge_answer(False)
        self.assertEqual(self.room.available_points(), 0)
        self.buzz(2)
        self.judge_answer(True)
        self.assertEqual(self.room.teams[2]["score"], 0)

    def test_zero_steals_means_one_attempt(self):
        self.room.steal_opportunities = 0
        self.pair()
        self.pick()
        self.buzz(0)
        self.judge_answer(False)
        self.assertEqual(self.room.phase, "board")

    def test_answers_only_sent_to_approved_judge_in_every_phase(self):
        pending = self.client()
        pending.emit("judge:join", {"code": self.code})
        self.pair()
        observer = self.client()
        observer.emit("player:request_state", {"code": self.code})
        self.pick()
        self.buzz(0)
        self.assertTrue(self.jobs)
        with patch.object(server.socketio, "sleep"):
            self.jobs[-1]()
        self.assertEqual(self.room.phase, "reveal")
        for client in (self.board, observer, *self.players, pending):
            for event in client.get_received():
                if event["name"] == "state" and event["args"][0]["current"]:
                    self.assertNotIn("answer", event["args"][0]["current"])
        states = [e["args"][0] for e in self.judge.get_received() if e["name"] == "state"]
        self.assertTrue(states)
        for state in (state for state in states if state["current"]):
            self.assertEqual(state["current"]["answer"], self.room.current["answer"])
        self.assertNotIn("judge_requests", self.room.public_state())
        self.assertNotIn("judge_token", self.room.judge_state())

    def test_only_board_can_approve_and_only_judge_can_score_steals(self):
        self.judge.emit("judge:join", {"code": self.code})
        pairing = next(iter(self.room.judge_requests.values()))
        self.players[0].emit("host:approve_judge", {"code": self.code, "pairing_code": pairing})
        self.assertIsNone(self.room.judge_sid)
        self.pair()
        self.pick()
        self.buzz(0)
        for client in (self.board, *self.players):
            client.emit("host:judge", {"code": self.code, "correct": True})
        self.assertEqual(self.room.teams[0]["score"], 0)
        self.board.emit("host:reveal_answer", {"code": self.code})
        self.board.emit("host:next", {"code": self.code})
        self.board.emit("host:cancel_question", {"code": self.code})
        self.assertEqual(self.room.phase, "buzzed")
        self.judge_answer(True)
        self.assertEqual(self.room.teams[0]["score"], 100)

    def test_judge_disconnect_blocks_play_and_token_restores_screen(self):
        token = self.pair()
        self.pick()
        self.judge.disconnect()
        self.buzz(0)
        self.assertEqual(self.room.phase, "question")
        replacement = self.client()
        replacement.emit("judge:join", {"code": self.code, "judge_token": token})
        self.assertTrue(self.room.screens_ready())
        self.buzz(0)
        self.assertEqual(self.room.phase, "buzzed")
        self.board.disconnect()
        replacement.emit("host:judge", {"code": self.code, "correct": True})
        self.assertEqual(self.room.teams[0]["score"], 0)

    def test_replacing_judge_revokes_old_socket_and_token(self):
        token = self.pair()
        old = self.judge
        self.judge = self.client()
        self.pair()
        self.pick()
        self.buzz(0)
        old.emit("host:judge", {"code": self.code, "correct": True})
        self.assertEqual(self.room.teams[0]["score"], 0)
        old.emit("judge:join", {"code": self.code, "judge_token": token})
        self.assertNotEqual(self.room.judge_sid, next(iter(self.room.judge_requests)))
        self.judge_answer(True)
        self.assertEqual(self.room.teams[0]["score"], 100)

    def test_skip_consumes_tile_without_awarding_and_resets_attempts(self):
        self.pair()
        self.pick()
        self.buzz(0)
        self.judge_answer(False)
        self.players[1].emit("host:skip_question", {"code": self.code})
        self.assertEqual(self.room.phase, "question")
        self.judge.emit("host:skip_question", {"code": self.code})
        self.assertEqual(self.room.phase, "board")
        self.assertIn((self.room.categories[0], 100), self.room.asked)
        self.pick(200)
        self.assertEqual(self.room.current["attempted_teams"], [])
        self.buzz(0)
        self.board.emit("host:skip_question", {"code": self.code})
        self.assertEqual(self.room.phase, "board")
        self.assertEqual(self.room.teams[0]["score"], 0)

    def test_skip_final_tile_ends_game(self):
        self.pair()
        self.pick()
        self.room.asked = {(q["category"], q["points"]) for q in self.room._tiles()}
        self.room.asked.remove((self.room.current["category"], self.room.current["points"]))
        self.board.emit("host:skip_question", {"code": self.code})
        self.assertEqual(self.room.phase, "ended")

    def test_old_timeout_does_not_expire_new_steal(self):
        self.pair()
        self.pick()
        self.buzz(0)
        old_timeout = self.jobs[-1]
        self.judge_answer(False)
        self.buzz(1)
        with patch.object(server.socketio, "sleep"):
            old_timeout()
        self.assertEqual(self.room.phase, "buzzed")
        with patch.object(server.socketio, "sleep"):
            self.jobs[-1]()
        self.assertEqual(self.room.phase, "reveal")
        self.judge_answer(True)
        self.assertEqual(self.room.teams[1]["score"], 75)

    def test_subtraction_keeps_wrong_answer_penalty_and_needs_no_judge(self):
        self.room.game_mode = "subtraction"
        self.pick()
        self.buzz(0)
        self.board.emit("host:reveal_answer", {"code": self.code})
        self.board.emit("host:judge", {"code": self.code, "correct": False})
        self.assertEqual(self.room.teams[0]["score"], -100)
        self.assertEqual(self.room.phase, "board")

    def test_invalid_settings_rejected_and_custom_values_persist(self):
        for settings in ({"game_mode": "other"}, {"game_mode": []}, {"steal_decrease": 0},
                         {"steal_decrease": 101}, {"steal_decrease": 2.5}, {"steal_decrease": True},
                         {"steal_opportunities": -1}, {"steal_opportunities": 15},
                         {"steal_opportunities": "2"}, {"steal_opportunities": None}):
            with self.subTest(settings=settings):
                response = self.http.post("/api/create", json={"question_set": "classic", **settings})
                self.assertEqual(response.status_code, 400)
        self.create(steal_decrease=15, steal_opportunities=4)
        self.assertEqual((self.room.steal_decrease, self.room.steal_opportunities), (15, 4))

    def test_judge_page_and_join_role_render(self):
        self.assertEqual(self.http.get(f"/judge/{self.code}").status_code, 200)
        self.assertIn('value="judge"', self.http.get("/join").get_data(as_text=True))
        self.assertEqual(self.http.get("/judge/missing").status_code, 302)
        self.room.game_mode = "subtraction"
        self.judge.emit("judge:join", {"code": self.code})
        self.assertIn("error", [e["name"] for e in self.judge.get_received()])

    def test_invalid_judge_token_gets_no_answers_and_requires_approval(self):
        self.judge.emit("judge:join", {"code": self.code, "judge_token": "invalid-🔑"})
        self.assertIsNone(self.room.judge_sid)
        self.assertIn("judge:pending", [e["name"] for e in self.judge.get_received()])

    def test_game_shutdown_reaches_private_host_and_clears_its_registration(self):
        self.pair()
        self.board.emit("host:cancel_game", {"code": self.code})
        self.assertIsNone(server.registry.get(self.code))
        self.assertFalse(server.registry.sid_to_judge)
        self.assertIn("game:cancelled", [e["name"] for e in self.judge.get_received()])


if __name__ == "__main__":
    unittest.main()

"""In-memory game state for JeoParty Online.

Keeps things simple: one process, one dict of rooms keyed by 6-digit code.
Not thread-safe; relies on Socket.IO/eventlet running everything on a single
greenlet.
"""

import random
import secrets
import time
from dataclasses import dataclass, field


def _new_code(existing):
    while True:
        code = f"{random.randint(0, 999999):06d}"
        if code not in existing:
            return code


@dataclass
class GameRoom:
    code: str
    host_token: str  # secret known only to the creator's browser
    host_sid: str | None = None
    question_set: str = ""
    set_name: str = ""
    categories: list = field(default_factory=list)
    questions: dict = field(default_factory=dict)  # {category: [{question, answer, points}, ...]}
    teams: list = field(default_factory=list)  # [{name, score}]
    question_time: int = 5
    phase: str = "lobby"  # lobby | board | question | buzzed | reveal | ended
    asked: set = field(default_factory=set)  # {(category, points)}
    current: dict | None = None
    players: dict = field(default_factory=dict)  # {player_id: {name, team, sid}}

    def public_state(self):
        """Snapshot safe to broadcast to players (no answers when not in reveal)."""
        teams_with_members = []
        for t in self.teams:
            members = [
                {"id": pid, "name": p["name"]}
                for pid, p in self.players.items()
                if p["team"] == t["name"]
            ]
            teams_with_members.append({
                "name": t["name"],
                "score": t["score"],
                "members": members,
            })

        current = None
        if self.current:
            current = {
                "category": self.current["category"],
                "points": self.current["points"],
                "question": self.current["question"],
                "buzzed_player": self.current.get("buzzed_player"),
                "buzzed_team": self.current.get("buzzed_team"),
            }
            # Only include answer once we're in reveal/buzzed phases
            if self.phase in ("reveal", "buzzed"):
                current["answer"] = self.current["answer"]

        return {
            "code": self.code,
            "phase": self.phase,
            "set_name": self.set_name,
            "categories": self.categories,
            "tiles": self._tiles(),
            "asked": [list(t) for t in self.asked],
            "teams": teams_with_members,
            "question_time": self.question_time,
            "current": current,
        }

    def host_state(self):
        """Snapshot for the host — same as public_state but always includes the answer."""
        state = self.public_state()
        if self.current and state["current"] is not None:
            state["current"]["answer"] = self.current["answer"]
        return state

    def _tiles(self):
        """Flat list of {category, points, asked} for the board grid."""
        tiles = []
        for cat in self.categories:
            for q in self.questions.get(cat, []):
                tiles.append({
                    "category": cat,
                    "points": q["points"],
                    "asked": (cat, q["points"]) in self.asked,
                })
        return tiles

    def find_question(self, category, points):
        for q in self.questions.get(category, []):
            if q["points"] == points:
                return q
        return None

    def team_by_name(self, name):
        for t in self.teams:
            if t["name"] == name:
                return t
        return None


class GameRegistry:
    def __init__(self):
        self.games: dict[str, GameRoom] = {}
        self.sid_to_player: dict[str, tuple[str, str]] = {}  # sid -> (code, player_id)
        self.sid_to_host: dict[str, str] = {}  # sid -> code

    def create(self, *, question_set, set_name, categories, questions, teams, question_time):
        code = _new_code(self.games)
        room = GameRoom(
            code=code,
            host_token=secrets.token_urlsafe(16),
            question_set=question_set,
            set_name=set_name,
            categories=list(categories),
            questions=questions,
            teams=[{"name": t, "score": 0} for t in teams],
            question_time=int(question_time),
        )
        self.games[code] = room
        return room

    def get(self, code):
        return self.games.get(code)

    def add_player(self, code, name, team_name, sid):
        room = self.games.get(code)
        if not room:
            return None, "game not found"
        if not room.team_by_name(team_name):
            return None, "team not found"
        # Reuse existing player_id if same name on same team is rejoining
        for pid, p in room.players.items():
            if p["name"] == name and p["team"] == team_name:
                p["sid"] = sid
                self.sid_to_player[sid] = (code, pid)
                return pid, None
        player_id = secrets.token_urlsafe(8)
        room.players[player_id] = {"name": name, "team": team_name, "sid": sid}
        self.sid_to_player[sid] = (code, player_id)
        return player_id, None

    def reconnect_player(self, code, player_id, sid):
        room = self.games.get(code)
        if not room or player_id not in room.players:
            return False
        room.players[player_id]["sid"] = sid
        self.sid_to_player[sid] = (code, player_id)
        return True

    def attach_host(self, code, host_token, sid):
        room = self.games.get(code)
        if not room or room.host_token != host_token:
            return False
        room.host_sid = sid
        self.sid_to_host[sid] = code
        return True

    def detach_sid(self, sid):
        """Called on socket disconnect; returns the affected room code (or None)."""
        if sid in self.sid_to_host:
            code = self.sid_to_host.pop(sid)
            room = self.games.get(code)
            if room and room.host_sid == sid:
                room.host_sid = None
            return code
        if sid in self.sid_to_player:
            code, _ = self.sid_to_player.pop(sid)
            return code
        return None

    def buzz(self, code, sid):
        """First-buzz-wins. Returns (room, player_id, team_name) on success, or (None, None, None)."""
        room = self.games.get(code)
        if not room or room.phase != "question" or not room.current:
            return None, None, None
        if room.current.get("buzzed_player"):
            return None, None, None
        if sid not in self.sid_to_player:
            return None, None, None
        c, pid = self.sid_to_player[sid]
        if c != code or pid not in room.players:
            return None, None, None
        player = room.players[pid]
        room.current["buzzed_player"] = pid
        room.current["buzzed_player_name"] = player["name"]
        room.current["buzzed_team"] = player["team"]
        room.current["buzz_ts"] = time.monotonic_ns()
        room.phase = "buzzed"
        return room, pid, player["team"]

"""In-memory game state for JeoParty Online.

Keeps things simple: one process, one dict of rooms keyed by 6-digit code.
Not thread-safe; relies on Socket.IO/eventlet running everything on a single
greenlet.
"""

import random
import secrets
import time
from dataclasses import dataclass, field


# 15 fixed team colors. Each has a background and a text color picked so text
# is readable against the background (white on dark, near-black on light).
TEAM_COLORS = [
    {"id": "red",         "bg": "#E53935", "fg": "#ffffff"},
    {"id": "pink",        "bg": "#EC407A", "fg": "#ffffff"},
    {"id": "purple",      "bg": "#8E24AA", "fg": "#ffffff"},
    {"id": "violet",      "bg": "#5E35B1", "fg": "#ffffff"},
    {"id": "indigo",      "bg": "#3949AB", "fg": "#ffffff"},
    {"id": "blue",        "bg": "#1E88E5", "fg": "#ffffff"},
    {"id": "cyan",        "bg": "#0097A7", "fg": "#ffffff"},
    {"id": "teal",        "bg": "#00796B", "fg": "#ffffff"},
    {"id": "green",       "bg": "#388E3C", "fg": "#ffffff"},
    {"id": "lime",        "bg": "#AFB42B", "fg": "#1a1a1a"},
    {"id": "yellow",      "bg": "#FDD835", "fg": "#1a1a1a"},
    {"id": "amber",       "bg": "#FFB300", "fg": "#1a1a1a"},
    {"id": "orange",      "bg": "#FB8C00", "fg": "#ffffff"},
    {"id": "deep_orange", "bg": "#F4511E", "fg": "#ffffff"},
    {"id": "brown",       "bg": "#6D4C41", "fg": "#ffffff"},
]
TEAM_COLORS_BY_ID = {c["id"]: c for c in TEAM_COLORS}
MAX_TEAMS = len(TEAM_COLORS)  # one distinct color per team
MAX_TEAM_NAME = 30

# Lobby cookie mini-game: a team eats a cookie in COOKIE_BITES bites, and each
# bite is 10 clicks counted on the player's own phone, so the server only hears
# about whole bites.
COOKIE_BITES = 10
MIN_BITE_INTERVAL = 0.4  # seconds; 10 clicks faster than this is a script, not a thumb


def _new_code(existing):
    while True:
        code = f"{random.randint(0, 999999):06d}"
        if code not in existing:
            return code


def _assign_team_colors(n):
    """Pick n color ids — distinct while the palette has room, then cycle."""
    pool = [c["id"] for c in TEAM_COLORS]
    random.shuffle(pool)
    if n <= len(pool):
        return pool[:n]
    out = list(pool)
    while len(out) < n:
        out.append(pool[(len(out) - len(pool)) % len(pool)])
    return out


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
    theme: str = "classic"  # classic | sunrise | neon
    cookies_enabled: bool = True  # lobby cookie mini-game and its rewards
    phase: str = "lobby"  # lobby | board | question | buzzed | reveal | ended
    asked: set = field(default_factory=set)  # {(category, points)}
    current: dict | None = None
    players: dict = field(default_factory=dict)  # {player_id: {name, team, sid}}
    picking_team: str | None = None  # team whose turn it is to pick the next tile

    def public_state(self):
        """Snapshot safe to broadcast to players (no answers when not in reveal)."""
        cookies = {c["name"]: c for c in self.cookie_state()}
        teams_with_members = []
        for t in self.teams:
            members = [
                {"id": pid, "name": p["name"]}
                for pid, p in self.players.items()
                if p["team"] == t["name"]
            ]
            color_id = t.get("color")
            color = TEAM_COLORS_BY_ID.get(color_id, TEAM_COLORS[0])
            teams_with_members.append({
                "name": t["name"],
                "score": t["score"],
                "members": members,
                "color": color_id,
                "color_bg": color["bg"],
                "color_fg": color["fg"],
                **cookies[t["name"]],
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
            # Only include answer once the timer has expired and answer is revealed
            if self.phase == "reveal":
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
            "theme": self.theme,
            "cookies_enabled": self.cookies_enabled,
            "current": current,
            "palette": TEAM_COLORS,
            "picking_team": self.picking_team,
        }

    def cookie_state(self):
        """Lobby cookie progress per team. The crown goes to whoever has eaten
        the most cookies (ties share it), once anyone has finished one."""
        best = max((t["cookies_eaten"] for t in self.teams), default=0)
        return [
            {
                "name": t["name"],
                "cookie_bites": t["cookie_bites"],
                "cookies_eaten": t["cookies_eaten"],
                "cookie_crown": best > 0 and t["cookies_eaten"] == best,
            }
            for t in self.teams
        ]

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

    def find_team(self, name):
        """Case-insensitive lookup, so "red" and "Red" are the same team."""
        key = name.casefold()
        for t in self.teams:
            if t["name"].casefold() == key:
                return t
        return None

    def add_team(self, name):
        """Create a team with an unused color. Returns (team, error_message)."""
        if len(self.teams) >= MAX_TEAMS:
            return None, f"this game already has the maximum of {MAX_TEAMS} teams"
        used = {t.get("color") for t in self.teams}
        free = [c["id"] for c in TEAM_COLORS if c["id"] not in used]
        team = {"name": name, "score": 0, "color": random.choice(free), "cookie_bites": 0, "cookies_eaten": 0}
        self.teams.append(team)
        if self.picking_team is None:
            self.picking_team = name
        return team, None

    def remove_team(self, name):
        self.teams = [t for t in self.teams if t["name"] != name]
        if self.picking_team == name:
            self.picking_team = self.teams[0]["name"] if self.teams else None


class GameRegistry:
    def __init__(self):
        self.games: dict[str, GameRoom] = {}
        self.sid_to_player: dict[str, tuple[str, str]] = {}  # sid -> (code, player_id)
        self.sid_to_host: dict[str, str] = {}  # sid -> code

    def create(self, *, question_set, set_name, categories, questions, teams=(), question_time, theme="classic",
               cookies_enabled=True):
        code = _new_code(self.games)
        team_color_ids = _assign_team_colors(len(teams))
        room = GameRoom(
            code=code,
            host_token=secrets.token_urlsafe(16),
            question_set=question_set,
            set_name=set_name,
            categories=list(categories),
            questions=questions,
            teams=[
                {"name": name, "score": 0, "color": color_id, "cookie_bites": 0, "cookies_eaten": 0}
                for name, color_id in zip(teams, team_color_ids)
            ],
            question_time=int(question_time),
            theme=theme,
            cookies_enabled=cookies_enabled,
        )
        room.picking_team = room.teams[0]["name"] if room.teams else None
        self.games[code] = room
        return room

    def change_team_color(self, code, team_name, color_id, sid):
        """Player on `team_name` swaps their team's color. Color must be in the
        palette and not already used by another team. Returns the room on
        success, or None on rejection."""
        room = self.games.get(code)
        if not room or color_id not in TEAM_COLORS_BY_ID:
            return None
        if sid not in self.sid_to_player:
            return None
        c, pid = self.sid_to_player[sid]
        if c != code or pid not in room.players:
            return None
        if room.players[pid]["team"] != team_name:
            return None
        for t in room.teams:
            if t["name"] != team_name and t.get("color") == color_id:
                return None
        team = room.team_by_name(team_name)
        if not team:
            return None
        team["color"] = color_id
        return room

    def get(self, code):
        return self.games.get(code)

    def delete(self, code):
        """Remove a room and forget every socket attached to it."""
        room = self.games.pop(code, None)
        if not room:
            return None
        self.sid_to_player = {s: v for s, v in self.sid_to_player.items() if v[0] != code}
        self.sid_to_host = {s: c for s, c in self.sid_to_host.items() if c != code}
        return room

    def add_player(self, code, name, team_name, sid, create_team=False):
        """Join `team_name`, creating it first if `create_team` is set and it doesn't exist.

        Returns (player_id, team_name, error_message); team_name is the existing
        team's spelling when a new-team request matches one case-insensitively.
        """
        room = self.games.get(code)
        if not room:
            return None, None, "game not found"
        team = room.find_team(team_name) if create_team else room.team_by_name(team_name)
        if not team and create_team:
            team, err = room.add_team(team_name[:MAX_TEAM_NAME])
            if err:
                return None, None, err
        if not team:
            return None, None, "team not found"
        team_name = team["name"]
        # Reuse existing player_id if same name on same team is rejoining
        for pid, p in room.players.items():
            if p["name"] == name and p["team"] == team_name:
                p["sid"] = sid
                self.sid_to_player[sid] = (code, pid)
                return pid, team_name, None
        player_id = secrets.token_urlsafe(8)
        room.players[player_id] = {"name": name, "team": team_name, "sid": sid}
        self.sid_to_player[sid] = (code, player_id)
        return player_id, team_name, None

    def remove_player(self, code, sid):
        """Take the player on this socket out of a game that's still in the lobby.

        A team left with no players is removed too. Returns the room, or None.
        """
        room = self.games.get(code)
        entry = self.sid_to_player.get(sid)
        if not room or room.phase != "lobby" or not entry or entry[0] != code:
            return None
        del self.sid_to_player[sid]
        player = room.players.pop(entry[1], None)
        if not player:
            return None
        if not any(p["team"] == player["team"] for p in room.players.values()):
            room.remove_team(player["team"])
        return room

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

    def cookie_bite(self, code, sid):
        """Player on this socket finished a bite of their team's lobby cookie.

        Bites belong to the team; the last bite of a cookie counts it as eaten
        and starts a fresh one. Returns the room, or None if the bite is ignored.
        """
        room = self.games.get(code)
        entry = self.sid_to_player.get(sid)
        if not room or not room.cookies_enabled or room.phase != "lobby" or not entry or entry[0] != code:
            return None
        player = room.players.get(entry[1])
        team = room.team_by_name(player["team"]) if player else None
        if not team:
            return None
        now = time.monotonic()
        if now - player.get("last_bite", float("-inf")) < MIN_BITE_INTERVAL:
            return None
        player["last_bite"] = now
        team["cookie_bites"] += 1
        if team["cookie_bites"] >= COOKIE_BITES:
            team["cookie_bites"] = 0
            team["cookies_eaten"] += 1
        return room

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
        room.picking_team = player["team"]
        return room, pid, player["team"]

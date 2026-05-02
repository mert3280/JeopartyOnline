"""JeoParty Online — Flask + Socket.IO server.

Run locally:
    pip install -r requirements.txt
    python server.py

Run in production (Render etc.):
    gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT server:app

Optional environment variables:
    PORT             port to bind (default 5000)
    NGROK_AUTHTOKEN  if set, opens an https tunnel via pyngrok on startup (local only)
    HOST             interface to bind (default 0.0.0.0)
    SECRET_KEY       Flask secret key (auto-generated on Render)
"""

import warnings
warnings.filterwarnings("ignore")  # silence eventlet's deprecation banner on import
import eventlet
eventlet.monkey_patch()  # must run before other imports for proper async behavior
warnings.resetwarnings()

import io
import os
import socket as stdlib_socket

import qrcode
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from flask_socketio import SocketIO, emit, join_room

import question_loader
from game_state import GameRegistry

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "jeoparty-dev-secret")
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")
registry = GameRegistry()


# ---------- network bootstrap ----------

def get_lan_ip():
    s = stdlib_socket.socket(stdlib_socket.AF_INET, stdlib_socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def maybe_open_tunnel(port):
    token = os.environ.get("NGROK_AUTHTOKEN")
    if not token:
        return None
    try:
        from pyngrok import conf, ngrok
        conf.get_default().auth_token = token
        tunnel = ngrok.connect(port, "http", bind_tls=True)
        return tunnel.public_url
    except Exception as e:
        print(f"[ngrok] tunnel failed, falling back to LAN: {e}")
        return None


# ---------- routes ----------

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/create")
def create_page():
    return render_template("create.html")


@app.route("/make-questions")
def make_questions_page():
    return render_template("make_questions.html")


@app.route("/api/question-sets", methods=["GET"])
def api_question_sets():
    return jsonify(question_loader.list_sets())


@app.route("/api/question-sets", methods=["POST"])
def api_save_question_set():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    categories = data.get("categories") or []
    questions = data.get("questions") or []

    if not name or len(name) > 60:
        return jsonify({"error": "name must be 1-60 characters"}), 400
    if not isinstance(categories, list) or len(categories) != 6:
        return jsonify({"error": "exactly 6 categories required"}), 400
    if any((not isinstance(c, str) or not c.strip() or len(c) > 60) for c in categories):
        return jsonify({"error": "every category needs a non-empty title (max 60 chars)"}), 400

    if not isinstance(questions, list) or len(questions) != 36:
        return jsonify({"error": "exactly 36 questions required (6 per category)"}), 400

    expected_points = {100, 200, 300, 400, 500, 600}
    by_cat = {str(i): set() for i in range(1, 7)}
    cleaned = []
    for q in questions:
        if not isinstance(q, dict):
            return jsonify({"error": "malformed question"}), 400
        cat = str(q.get("category", "")).strip()
        question = str(q.get("question", "")).strip()
        answer = str(q.get("answer", "")).strip()
        try:
            points = int(q.get("points"))
        except (TypeError, ValueError):
            return jsonify({"error": "question points must be a number"}), 400
        if cat not in by_cat:
            return jsonify({"error": "category index must be 1-6"}), 400
        if not question or not answer:
            return jsonify({"error": "every question needs a question and answer"}), 400
        if points not in expected_points:
            return jsonify({"error": "question points must be one of 100-600"}), 400
        if points in by_cat[cat]:
            return jsonify({"error": f"duplicate points {points} in category {cat}"}), 400
        by_cat[cat].add(points)
        cleaned.append({
            "category": cat,
            "question": question[:500],
            "answer": answer[:200],
            "points": points,
        })

    for cat, pts in by_cat.items():
        if pts != expected_points:
            return jsonify({"error": f"category {cat} is missing one of the point tiers"}), 400

    cleaned_categories = [c.strip()[:60] for c in categories]
    try:
        stem, saved_name = question_loader.save_set(name, cleaned_categories, cleaned)
    except OSError as e:
        return jsonify({"error": f"could not save: {e}"}), 500

    return jsonify({"filename": stem, "name": saved_name}), 201


@app.route("/api/create", methods=["POST"])
def api_create():
    data = request.get_json(force=True, silent=True) or {}
    set_filename = data.get("question_set", "").strip()
    teams = [t.strip() for t in data.get("teams", []) if t and t.strip()]
    question_time = int(data.get("question_time") or 5)
    theme = (data.get("theme") or "sunrise").strip()

    if not set_filename:
        return jsonify({"error": "missing question_set"}), 400
    if len(teams) < 1:
        return jsonify({"error": "need at least one team"}), 400
    if len(set(teams)) != len(teams):
        return jsonify({"error": "team names must be unique"}), 400
    if question_time < 1 or question_time > 120:
        return jsonify({"error": "question_time must be between 1 and 120"}), 400
    if theme not in {"sunrise", "kahoot", "neon"}:
        theme = "sunrise"

    try:
        bundle = question_loader.load_set(set_filename)
    except FileNotFoundError:
        return jsonify({"error": "question set not found"}), 404

    room = registry.create(
        question_set=set_filename,
        set_name=bundle["name"],
        categories=bundle["categories"],
        questions=bundle["questions_by_category"],
        teams=teams,
        question_time=question_time,
        theme=theme,
    )

    return jsonify({
        "code": room.code,
        "host_token": room.host_token,
        "host_url": url_for("host_page", code=room.code, _external=False),
    })


@app.route("/host/<code>")
def host_page(code):
    room = registry.get(code)
    if not room:
        abort(404)
    return render_template(
        "host.html",
        code=code,
        public_url=app.config.get("PUBLIC_URL", ""),
        theme=room.theme,
    )


@app.route("/host/<code>/qr.png")
def host_qr(code):
    room = registry.get(code)
    if not room:
        abort(404)
    base = app.config.get("PUBLIC_URL") or request.host_url.rstrip("/")
    join_url = f"{base}/join?code={code}"
    img = qrcode.make(join_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/join")
def join_page():
    return render_template("join.html", prefill=request.args.get("code", ""))


@app.route("/play/<code>")
def play_page(code):
    room = registry.get(code)
    if not room:
        return redirect(url_for("join_page"))
    return render_template("play.html", code=code)


# ---------- helpers ----------

def broadcast_state(room):
    """Push state to host (with answer) and players (without, until reveal/buzzed)."""
    public = room.public_state()
    socketio.emit("state", public, room=f"players:{room.code}")
    if room.host_sid:
        socketio.emit("state", room.host_state(), room=room.host_sid)


def schedule_buzz_timeout(room):
    """After a player buzzes, transition to reveal when answer time runs out."""
    deadline_seconds = room.question_time
    expected_qid = (room.current["category"], room.current["points"]) if room.current else None
    expected_player = room.current.get("buzzed_player") if room.current else None

    def _timeout():
        socketio.sleep(deadline_seconds)
        if (
            room.phase == "buzzed"
            and room.current
            and (room.current["category"], room.current["points"]) == expected_qid
            and room.current.get("buzzed_player") == expected_player
        ):
            room.phase = "reveal"
            broadcast_state(room)

    socketio.start_background_task(_timeout)


# ---------- socket handlers ----------

@socketio.on("connect")
def on_connect():
    pass


@socketio.on("disconnect")
def on_disconnect():
    code = registry.detach_sid(request.sid)
    if code:
        room = registry.get(code)
        if room:
            broadcast_state(room)


@socketio.on("host:join")
def on_host_join(data):
    code = (data or {}).get("code")
    token = (data or {}).get("host_token")
    if not registry.attach_host(code, token, request.sid):
        emit("error", {"message": "host auth failed"})
        return
    join_room(request.sid)  # implicit, but explicit doesn't hurt
    room = registry.get(code)
    emit("state", room.host_state())


@socketio.on("host:start_game")
def on_host_start(data):
    code = (data or {}).get("code")
    room = registry.get(code)
    if not room or room.host_sid != request.sid:
        return
    if room.phase == "lobby":
        room.phase = "board"
        broadcast_state(room)


@socketio.on("host:pick_question")
def on_host_pick(data):
    code = (data or {}).get("code")
    category = (data or {}).get("category")
    points = (data or {}).get("points")
    room = registry.get(code)
    if not room or room.host_sid != request.sid:
        return
    if room.phase != "board":
        return
    if (category, points) in room.asked:
        return
    q = room.find_question(category, int(points))
    if not q:
        return
    room.current = {
        "category": category,
        "points": int(points),
        "question": q["question"],
        "answer": q["answer"],
        "buzzed_player": None,
        "buzzed_team": None,
    }
    room.phase = "question"
    broadcast_state(room)


@socketio.on("host:reveal_answer")
def on_host_reveal(data):
    code = (data or {}).get("code")
    room = registry.get(code)
    if not room or room.host_sid != request.sid or not room.current:
        return
    if room.phase in ("question", "buzzed"):
        room.phase = "reveal"
        broadcast_state(room)


@socketio.on("host:judge")
def on_host_judge(data):
    code = (data or {}).get("code")
    correct = bool((data or {}).get("correct"))
    room = registry.get(code)
    if not room or room.host_sid != request.sid or not room.current:
        return
    if room.phase != "reveal":
        return
    team = room.team_by_name(room.current["buzzed_team"])
    if team:
        team["score"] += room.current["points"] if correct else -room.current["points"]
    room.asked.add((room.current["category"], room.current["points"]))
    room.current = None
    room.phase = "ended" if _is_game_over(room) else "board"
    broadcast_state(room)


@socketio.on("host:next")
def on_host_next(data):
    """Move on after a no-buzz reveal."""
    code = (data or {}).get("code")
    room = registry.get(code)
    if not room or room.host_sid != request.sid or not room.current:
        return
    if room.phase != "reveal":
        return
    room.asked.add((room.current["category"], room.current["points"]))
    room.current = None
    room.phase = "ended" if _is_game_over(room) else "board"
    broadcast_state(room)


@socketio.on("host:cancel_question")
def on_host_cancel(data):
    code = (data or {}).get("code")
    room = registry.get(code)
    if not room or room.host_sid != request.sid:
        return
    if room.phase in ("question", "buzzed", "reveal"):
        room.current = None
        room.phase = "board"
        broadcast_state(room)


@socketio.on("host:edit_score")
def on_host_edit_score(data):
    code = (data or {}).get("code")
    team_name = (data or {}).get("team")
    new_score = (data or {}).get("score")
    room = registry.get(code)
    if not room or room.host_sid != request.sid:
        return
    team = room.team_by_name(team_name)
    if team is None:
        return
    try:
        team["score"] = int(new_score)
    except (TypeError, ValueError):
        return
    broadcast_state(room)


@socketio.on("player:request_state")
def on_player_request_state(data):
    """Send public state to a new player before they've joined, so they can see team options."""
    code = (data or {}).get("code")
    room = registry.get(code)
    if room:
        emit("state", room.public_state())


@socketio.on("player:join")
def on_player_join(data):
    code = (data or {}).get("code")
    name = (data or {}).get("name", "").strip()
    team = (data or {}).get("team", "").strip()
    if not (code and name and team):
        emit("error", {"message": "missing fields"})
        return
    if len(name) > 30:
        name = name[:30]
    player_id, err = registry.add_player(code, name, team, request.sid)
    if err:
        emit("error", {"message": err})
        return
    join_room(f"players:{code}")
    emit("joined", {"player_id": player_id})
    room = registry.get(code)
    broadcast_state(room)


@socketio.on("player:reconnect")
def on_player_reconnect(data):
    code = (data or {}).get("code")
    player_id = (data or {}).get("player_id")
    if not (code and player_id):
        emit("reconnected", {"ok": False})
        return
    if registry.reconnect_player(code, player_id, request.sid):
        join_room(f"players:{code}")
        emit("reconnected", {"ok": True, "player_id": player_id})
        room = registry.get(code)
        broadcast_state(room)
    else:
        emit("reconnected", {"ok": False})


@socketio.on("player:buzz")
def on_player_buzz(data):
    code = (data or {}).get("code")
    room, player_id, team_name = registry.buzz(code, request.sid)
    if not room:
        return
    socketio.emit(
        "buzz_result",
        {
            "player_id": player_id,
            "player_name": room.current["buzzed_player_name"],
            "team": team_name,
        },
        room=f"players:{code}",
    )
    broadcast_state(room)
    schedule_buzz_timeout(room)


def _is_game_over(room):
    total_tiles = sum(len(qs) for qs in room.questions.values())
    return len(room.asked) >= total_tiles


# ---------- entrypoint ----------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")

    public_url = maybe_open_tunnel(port)
    lan_ip = get_lan_ip()
    lan_url = f"http://{lan_ip}:{port}"
    app.config["PUBLIC_URL"] = public_url or lan_url

    print("=" * 60)
    print(" JeoParty Online")
    print("=" * 60)
    if public_url:
        print(f" Public URL (anywhere):  {public_url}")
    print(f" LAN URL (same wifi):    {lan_url}")
    print(f" Local URL:              http://127.0.0.1:{port}")
    print("=" * 60)

    socketio.run(app, host=host, port=port, debug=False)

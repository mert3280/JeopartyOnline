# JeoParty Online

Web-based multiplayer port of the original tkinter game ([mainSC.py](mainSC.py)). The host runs a server on their laptop; players join from their phones via a 6-digit code or by scanning a QR. Answering is buzzer-based — first phone to tap wins.

## Quick start

```bash
pip install -r requirements.txt
python server.py
```

The console prints two URLs on startup:

```
 LAN URL (same wifi):    http://192.168.x.x:5000
 Local URL:              http://127.0.0.1:5000
```

Open the LAN URL on your laptop in a browser and click **Create Game**. Phones on the same wifi can also use that URL — or just scan the QR code shown on the host page.

### Joining from anywhere (not just same wifi)

Set an `NGROK_AUTHTOKEN` env var (free from [dashboard.ngrok.com](https://dashboard.ngrok.com)) and `server.py` will open an https tunnel on startup so phones can join over cellular too:

```bash
# bash
NGROK_AUTHTOKEN=<your_token> python server.py

# powershell
$env:NGROK_AUTHTOKEN = "<your_token>"; python server.py
```

The host page's QR will then encode the public ngrok URL.

## Deploying to Render (free tier)

For an always-on, internet-accessible deploy without running anything on your laptop:

1. Push this repo to GitHub.
2. At [render.com](https://render.com), sign up and pick **New → Blueprint** → connect the repo. Render reads [render.yaml](render.yaml) and provisions one free web service.
3. Wait for the first build (~3 minutes). Done — your game is live at `https://<service-name>.onrender.com`.

To use a custom domain:
- In the Render service's **Settings → Custom Domains**, add `jeoparty.yourdomain.com`.
- Render shows a CNAME target; add it as a CNAME record in your domain registrar's DNS.
- Render handles HTTPS automatically.

**Free tier behaviour:** the service sleeps after 15 minutes of inactivity. The first request after sleep takes ~30–60 seconds to wake the container. For game-night usage, just hit the site a minute before guests show up to warm it up. Game state lives in memory, so a service restart wipes any active game — fine for one-and-done sessions.

**Adding a question set after deploy:** since `questions/` is part of the repo, drop a new JSON file in, commit, and push. Render redeploys automatically (~2 min).

## Adding question sets

Drop a `*.json` file into the [questions/](questions) folder. The schema matches the original `questions.json`:

```json
{
  "name": "My Game Pack",
  "categories": ["Cat 1", "Cat 2", "Cat 3", "Cat 4", "Cat 5", "Cat 6"],
  "questions": [
    { "category": "1", "question": "...", "answer": "...", "points": 100 },
    ...
  ]
}
```

- `name` is optional (filename stem is used otherwise).
- `category` is a 1-indexed string into the `categories` array.
- 6 categories required, typically 6 questions per category (100/200/300/400/500/600 points).

The host's create-game page lists every valid file from `questions/` in a dropdown.

## How a game runs

1. Host opens `/`, clicks **Create Game**, picks a question set, adds team names, sets the question timer (default 5s), and submits → lands on the host page with a 6-digit code and QR.
2. Players visit `/` on their phone, enter the code (or scan the QR), enter their name, and pick a team.
3. Host sees players appear under each team in the lobby. Click **Start Game** when ready.
4. Host clicks a tile → the question shows on every screen. The countdown ticks down on the host's modal. Phones get a big red **BUZZ** button.
5. First phone to tap **BUZZ** wins. The host sees who buzzed and clicks **Correct** (+points) or **Wrong** (-points).
6. If the timer expires with no buzzes, the host clicks **Reveal Answer** then **Next**.
7. Repeat until all 36 tiles are used; final standings appear automatically.

The host can also click any team's score chip in the header to manually edit it.

## Troubleshooting

- **"No question sets found"** — make sure at least one `*.json` file exists in `questions/` and has a `categories` array of length 6.
- **Phones can't connect on LAN** — your laptop's firewall is probably blocking port 5000. Allow Python through the firewall, or set the `PORT` env var to one that's open.
- **Host page says "Host token missing"** — open the host link in the same browser that created the game. The host token lives in `localStorage`. To recover, just create a new game.
- **ngrok fails to start** — check the token is correct and that you haven't hit ngrok's free-tier session limit. The server falls back to LAN-only without crashing.

## File layout

```
server.py            Flask + Socket.IO server, route handlers, tunnel bootstrap
game_state.py        GameRoom + GameRegistry (in-memory state)
question_loader.py   Discovers and parses questions/*.json
questions/           Question-set JSON files (drop new ones here)
templates/           Jinja templates: landing / create / host / join / play
static/
  css/main.css       Shared theme + responsive rules
  js/{host,play,create}.js
mainSC.py            Original tkinter game, kept as reference
```

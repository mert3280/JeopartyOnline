# JeoParty Online

Multiplayer trivia with a host board and phone buzzers. Players join with a
six-digit code or QR code. MongoDB stores question packs; Flask + Socket.IO runs
the live game.



## Run locally with MongoDB

Run these commands from the folder containing `server.py`:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env with your MongoDB connection URI, then:
python server.py
```

If `.env` already exists, keep it instead of copying over it. `.env` and
`DB_info.md` are ignored by Git. Never put credentials in source files or browser
JavaScript. `DB_info.md` is a private reference, not a runtime configuration file.

The server loads `.env` automatically. Set:

```dotenv
QUESTION_STORAGE=mongodb
MONGODB_URI=mongodb+srv://USERNAME:PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=jeoparty
MASTER_PASSWORD='choose-a-password'
```

Every new set needs a creator password, chosen in the builder or as the
`"password"` field of an uploaded JSON file. It is stored in plain text with the set
but never sent to browsers or included in downloads. Editing, renaming or deleting
a set requires its creator password or `MASTER_PASSWORD`. Sets without a creator
password (such as the bundled packs) can only be changed with the master password.
`DELETE_PASSWORD` is still accepted as an older name for `MASTER_PASSWORD`.
Anyone can view, download and upload sets. The **Question Sets** page offers a JSON
template to fill in offline and upload.

Percent-encode special characters in the URI's username and password. Environment
variables supplied by your hosting provider take precedence over `.env`.

On the first question-storage request after startup, existing `questions/*.json`
packs are imported into `jeoparty.question_sets`. Importing again preserves
existing documents, so restarts and redeploys do not overwrite packs. Each pack
is one document containing its name, six categories, and questions/answers.
The filename stem becomes its unique `_id`.

With MongoDB configured, listing, loading, and saving packs use MongoDB. A database
outage returns an error instead of silently saving to temporary disk. Packs made
through **Question Sets** survive server restarts. A new pack with an existing
name gets a suffix (`my-pack-2`, etc.).

Without MongoDB settings, local development uses the `questions/` JSON folder.
Set `QUESTION_STORAGE=json` explicitly to use that mode with a local `.env`.

## Play over Wi-Fi and cellular data

MongoDB provides storage. Players still need a public URL for the game server.
Choose either a hosted server or a tunnel from your laptop. Host and players must
all use the same server, since active rooms live in its memory.

### Deploy to Render

[Deploy this repository to Render](https://render.com/deploy?repo=https://github.com/mert3280/JeopartyOnline)

1. Push the application repository to GitHub.
2. In Render, create a **Blueprint** from the repository. The included
   `render.yaml` runs one web service with WebSocket support.
3. Enter the real `MONGODB_URI` and a `MASTER_PASSWORD` when prompted. The blueprint sets
   `QUESTION_STORAGE=mongodb` and `MONGODB_DATABASE=jeoparty`.
4. Add the service's outbound IP ranges to Atlas as described below. If the
   initial health check fails before Atlas allows access, fix the access list
   and redeploy.
5. Open `https://<service-name>.onrender.com`, create a game there, and share its
   join link or QR code. Players can use other Wi-Fi networks or cellular data.

For an existing Render service, set those environment variables manually and set
`TRUST_PROXY=1`. The server uses `RENDER_EXTERNAL_URL` automatically for public
join links. For a custom domain, set `PUBLIC_URL=https://your-domain.example`.

Keep **one worker and one service instance**. MongoDB persists question packs;
active rooms, scores, and player connections remain in memory and reset when the
server restarts. Multiple instances would require shared room state and a
Socket.IO message broker. Free hosting may sleep when idle; visit the site before
starting a game. This repository change does not itself create a live deployment.

See [Render Flask hosting](https://render.com/docs/deploy-flask) and
[WebSocket support](https://render.com/docs/websocket).

### Connect a GoDaddy domain

For this project, use `jeopartyonline.com` as the main address and
`https://jeopartyonline.com` as `PUBLIC_URL` after domain verification. The
existing Render service is
[`srv-d7nfsuog4nts73b56pt0`](https://dashboard.render.com/web/srv-d7nfsuog4nts73b56pt0/settings).
Use that service rather than creating a duplicate from the deployment shortcut.

First get the game working at its actual Render `onrender.com` address. In the
Render service, go to **Settings → Custom Domains → Add Custom Domain** and add
the address you want players to use.

If your domain uses GoDaddy nameservers, open **GoDaddy Domain Portfolio → your
domain → DNS → DNS Records**. For a root domain such as `example.com`, the usual
records are:

| Type | Name | Value |
| --- | --- | --- |
| A | `@` | `216.24.57.1` |
| CNAME | `www` | The service's actual `onrender.com` hostname |

For a subdomain such as `play.example.com`, use a CNAME named `play` pointing to
that Render hostname. A CNAME value is a hostname, with no `https://` or path.
Use the exact records Render displays for your service. Replace conflicting
website records at those names, including parking/forwarding records and AAAA
records for the address being connected. Preserve email MX/TXT records.

Return to Render and click **Verify** for the domain. Once verification and HTTPS
are ready, set `PUBLIC_URL=https://your-real-domain` in the service's
**Environment** settings and deploy the change. New join links and QR codes then
use your domain. No separate SSL certificate purchase is needed.

See [Render's domain setup](https://render.com/docs/custom-domains),
[DNS record requirements](https://render.com/docs/configure-other-dns), and
[GoDaddy's CNAME instructions](https://www.godaddy.com/help/add-a-cname-record-19236).

### Run on your laptop with ngrok

Add `NGROK_AUTHTOKEN=your-token` to `.env`, then run `python server.py`.
The console prints a public HTTPS URL, and the host's join link/QR uses it.
Keep the laptop and server running during the game. You can obtain a token at
[ngrok's dashboard](https://dashboard.ngrok.com).

Without public hosting or a tunnel, the printed LAN URL works on the same Wi-Fi
only. A game code identifies a room on that server; it does not make a private
server reachable from the internet.

## MongoDB Atlas portal settings

- **Database Access:** the application's database user needs `readWrite` on the
  `jeoparty` database. Atlas website login accounts and database users are separate.
- **Network Access / IP Access List:** allow your laptop's public IP for local
  development. For Render, open the service's **Connect → Outbound** tab and add
  **all** listed outbound IP ranges to Atlas. Only the game server connects to
  MongoDB; players' phone IPs do not need access.
- You do not need to create collections or indexes manually. The app creates
  `question_sets` on first import, using MongoDB's built-in unique `_id` index.

See [Atlas IP access lists](https://www.mongodb.com/docs/atlas/security/add-ip-address-to-list/)
and [finding Render outbound IP ranges](https://render.com/docs/outbound-ip-addresses).

## Playing

1. The host opens **Create Game**, selects a pack and theme, and creates a room.
2. Players open the public join link, enter their names, and join a team or
   create a new one. In the lobby they can go back to pick a different team or
   leave the game. If the host cancels the game, everyone is sent home.
3. The host starts the game and selects a tile. The first player to buzz wins.
4. After the answer timer, the host judges the answer or moves to the next tile.
5. Final standings appear when all tiles have been used. The host can also edit
   team scores by clicking a score chip.

## Hosting from a phone, tablet, or any browser

The host screen is fully responsive. On a public deploy (Render) or ngrok tunnel,
anyone can create and run a game from any device with a browser:

- **Phone portrait**: each category becomes its own card with a row of point tiles;
  Correct/Wrong are big tap targets.
- **Phone landscape / tablet / laptop**: the classic 6×6 board.
- The host page keeps the screen awake (Wake Lock API, where supported) and shows a
  **Reconnecting…** banner if the connection drops. It re-authenticates on its own
  when the connection comes back.

**Switching devices mid-game:** tap **Host from another device** (lobby) or
**Switch device** (board), then scan the QR or open/share the link on the new device.
It takes over, and the old screen shows "Hosting moved" with a **Take control here**
button. The link carries the room's host key in the `#` fragment (never sent to the
server). Anyone with it can run the game, so only send it to yourself or a co-host.

## Adding packs

Use **Make Questions** to save a pack directly into the configured storage.
Alternatively, add a JSON file to `questions/` and restart the server to import it:

```json
{
  "name": "My Pack",
  "categories": ["Cat 1", "Cat 2", "Cat 3", "Cat 4", "Cat 5", "Cat 6"],
  "questions": [
    {"category": "1", "question": "Example clue", "answer": "Example answer", "points": 100}
  ]
}
```

A full board needs six questions per category, worth 100 through 600 points.
`category` is the 1-based category number. Existing MongoDB packs are preserved
when importing JSON with the same filename stem; edit existing packs directly
in Atlas if necessary.

## Troubleshooting and checks

- **Question storage unavailable:** check Atlas access lists, the database user's
  password/role, and `MONGODB_URI`. A DNS error means the server cannot resolve
  the cluster's SRV records. `/healthz` returns HTTP 200 when storage works and
  HTTP 503 when MongoDB is unavailable. Its `question_storage` field reports
  `mongodb` or `json`; a production MongoDB deployment should report `mongodb`.
  A healthy response with `json` means the server is still using local files.
- **Phones cannot join:** open the public HTTPS URL on the phone. A `192.168.*`
  or `127.0.0.1` link cannot be used over cellular data.
- **Host token missing:** open the host link in the browser that created it.
- **ngrok fails:** check its token and account limits. The console indicates when
  the server falls back to LAN access.

Run the automated checks with `python -m unittest discover -s tests -v`.

## Files

```text
server.py            Flask + Socket.IO routes, network bootstrap
database.py          Server-side MongoDB configuration and client
question_loader.py   MongoDB/JSON storage, automatic import, game pack parsing
game_state.py        In-memory game rooms and buzzer state
questions/           Bundled packs imported without overwriting MongoDB packs
templates/           Landing, creator, host, join, player, question editor pages
static/              Browser JavaScript and CSS
render.yaml          Public hosting blueprint (credentials supplied separately)
mainSC.py            Original desktop game, retained as reference
```

# assaee-api

Backend for [As-Sa'ee](https://github.com/as-saee/assaee-docs): a FastAPI service that will grow into a modular
monolith plus a worker. The first feature is the **heartbeat**: it notices when something you started has gone quiet
for longer than your own rhythm and brings it back gently, with no streaks and no guilt.

> **No authentication yet.** Login arrives with Keycloak in milestone M4. Until then, run the API locally only and do
> not expose it to the internet.

## How the heartbeat works
- A **thread** is anything you want to keep alive: a book, a project, training, research. Creating one needs only a
  name; each *kind* has a starting rhythm (book 24 h, project 24 h, gym 72 h, research 168 h, other 72 h).
- Every **touch** (one tap) is recorded. After a few touches the thread uses your *real* rhythm: the median gap
  between the days you touched it, so an off week does not distort it and several touches in one day count once.
- A thread is **quiet** once the gap is 1.5× its usual gap. It can only **nudge** on its active weekdays, outside quiet
  hours (22:00–07:00 local by default), and not while snoozed or paused.
- Each snooze counts as an ignored nudge and widens that thread's threshold (capped at 3×); a touch resets it.
- `GET /nudges` returns at most `ASSAEE_NUDGE_CAP` (default 3) nudges, most overdue first, plus one grouped summary of
  the rest. Messages are plain: `Book: last touched 3 days ago`.

The rules are pure functions in [`app/heartbeat.py`](app/heartbeat.py), tested without a database or a clock.

## API
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| POST / GET | `/threads` | create (name only is enough) / list with status |
| PATCH / DELETE | `/threads/{id}` | rename, set rhythm or active days (`interval_hours: null` returns to the learned rhythm) / soft delete |
| POST | `/threads/{id}/touch` | record a touch |
| POST | `/threads/{id}/snooze` | `{"hours": n}` |
| POST | `/threads/{id}/pause`, `/resume` | `{"until": "<ISO time with offset>"}` / clear |
| GET | `/nudges` | what to say right now |
| POST | `/nudges/send` | publish the current nudges to ntfy (503 if `ASSAEE_NTFY_URL` is unset, 502 if ntfy is unreachable) |

Interactive docs at `/docs` while the server runs.

## Run
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export ASSAEE_API_KEY=dev-key     # any value locally; use a long random one in production
uvicorn app.main:app --reload     # data in ./assaee.db
pytest -q && ruff check . && ruff format --check .
```
Or `docker compose up --build` (data in a named volume, bound to `127.0.0.1`).

| Variable | Default | Meaning |
|---|---|---|
| `ASSAEE_DB_URL` | `sqlite:///./assaee.db` | database (SQLite until the move to PostgreSQL in M3) |
| `ASSAEE_API_KEY` | _(required)_ | shared secret; send it as `Authorization: Bearer <key>` on every route except `/health`. The server refuses to start without it |
| `ASSAEE_TZ` | `Europe/Madrid` | timezone for active days and quiet hours |
| `ASSAEE_NTFY_URL` | _(empty: delivery off)_ | base URL of the [ntfy](https://ntfy.sh) server (`http://ntfy` in compose) |
| `ASSAEE_NTFY_TOKEN` | _(empty)_ | write-only ntfy access token; required because ntfy denies anonymous access |
| `ASSAEE_NTFY_TOPIC` | `assaee-nudges` | ntfy topic the phone subscribes to |
| `ASSAEE_NTFY_BIND` | `127.0.0.1` | address the ntfy port listens on (compose only). Set it to the host's Tailscale IP to reach ntfy from a phone on the tailnet |
| `ASSAEE_NUDGE_CAP` | `3` | most nudges per request |
| `ASSAEE_QUIET_START` / `ASSAEE_QUIET_END` | `22` / `7` | local quiet hours |

## Protecting ntfy
ntfy runs with default access `deny-all`: nothing works until a user is allowed. Two identities, least privilege:
the API may only **write** to the topic, the phone may only **read** it. Create them once after the first start
(passwords are read from `NTFY_PASSWORD`, so they stay out of shell history):
```bash
NTFY_PASSWORD='<phone password>' docker compose exec -e NTFY_PASSWORD ntfy ntfy user add phone
NTFY_PASSWORD='<api password>'   docker compose exec -e NTFY_PASSWORD ntfy ntfy user add apipub
docker compose exec ntfy ntfy access phone  assaee-nudges read-only
docker compose exec ntfy ntfy access apipub assaee-nudges write-only
docker compose exec ntfy ntfy token add apipub    # prints tk_...; set it as ASSAEE_NTFY_TOKEN
```
Subscribe in the ntfy app with the `phone` user. Verified against the real server: anonymous access, reading with
the API token, and publishing as the phone are all refused (403).

## Reaching ntfy from a phone
ntfy listens on `127.0.0.1` by default, so only the host can reach it. To use a phone, put both devices on a
[Tailscale](https://tailscale.com) tailnet and bind the port to the host's tailnet address only (never `0.0.0.0`):
```bash
printf '\nASSAEE_NTFY_BIND=%s\n' "$(tailscale ip -4)" >> .env   # leading \n: .env may lack a final newline
docker compose up -d
```
In the ntfy app add the server `http://<tailnet IP>:2586` with the `phone` user and subscribe to `assaee-nudges`.
Traffic is encrypted by Tailscale. Keep the phone's VPN on and exempt ntfy from Android battery limits.
Verified end to end: a message published from the host appeared on an Android phone immediately.

## Not built yet
Push delivery (self-hosted ntfy with a "Done" action), the capture inbox, per-user login (Keycloak, M4), and the Postgres migration.
See the [roadmap](https://github.com/as-saee/assaee-docs/blob/main/docs/roadmap.md).

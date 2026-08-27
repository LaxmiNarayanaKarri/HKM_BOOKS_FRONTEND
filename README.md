# FNRG Preaching — Frontend

Flask frontend for your two FastAPI services:
- **Users service** → `http://localhost:8000`
- **Books service** → `http://localhost:8001`

## What I found in the original zip

- `app.py` had plain Flask routes (`/`, `/login`, `/users`, ...) but every
  template calls blueprint-style endpoints (`url_for('books.dashboard')`,
  `url_for('users.login')`, `url_for('books.master_data_add_book')`, ~20
  in total). The two didn't match — the app would 500 on almost every page.
- `analytics.py` and `dummy_data.py` were referenced by leftover
  `__pycache__/*.pyc` files but missing as source. I decompiled the
  bytecode to recover the data shapes the templates expect (sales rows,
  users, books) and used that to figure out what each route needs to pass
  in — no dummy data or in-memory lists made it into the new app.

## What's rebuilt

- `app.py` — application factory, registers two blueprints, injects
  `current_user` into every template.
- `blueprints/users.py` → talks to the **users service**.
- `blueprints/books.py` → talks to the **books service**.
- `services/api_client.py` — shared `requests` wrapper: builds
  `X-User` / `X-Role` headers from the session (per the docstring in the
  `users.py` router you sent: *"X-User/X-Role resolved via
  app.core.auth"*), raises a clean `BackendError` on failure so routes
  can flash a message instead of crashing.
- Templates and static files are **untouched** — same UI, same CSS/JS.

## Wired to your real contract (users service)

Everything in `blueprints/users.py` under `/users*` matches the
`app/api/routers/users.py` you sent, byte for byte:

| Flask route | FastAPI endpoint |
|---|---|
| `GET/POST /users` | `GET/POST /api/users` |
| `GET /users/export` | `GET /api/users/export` |
| `POST /users/<u>/toggle` | `POST /api/users/{username}/toggle` |
| `POST /users/<u>/delete` | `POST /api/users/{username}/delete` |
| `POST /users/<u>/password` | `POST /api/users/{username}/password` |
| `POST /users/<u>/role` | `POST /api/users/{username}/role` |

## Still placeholders (need the router source to finish)

I don't have `auth.py`, `volunteers.py` (users service) or
`catalog.py` / `dashboard.py` / `sell.py` / `backup.py` /
`inward_stock.py` / `master_data.py` (books service) yet, so those
routes call **best-guess** endpoint paths, clearly marked
`# PLACEHOLDER` in the code, with the assumed request/response shape
described right above each call. Every one of them fails gracefully —
if the guessed path is wrong, you'll see a flashed error banner instead
of a crash, and the page still renders with empty tables.

**To finish it yourself** (same pattern as `users.py`, which is done):
1. Open the corresponding router file on the backend, note the real path
   + payload shape.
2. In `blueprints/books.py` (or the two remaining stubs in `users.py`:
   `login()` and `volunteer_assignment()`), swap the guessed path/`json=`
   payload for the real one.
3. That's it — the request/response plumbing (`get_json`/`post_json`/
   `get_file` in `services/api_client.py`) already handles auth headers,
   errors, and file downloads.

Or just paste me the router source (or `/openapi.json`) for any of
those and I'll wire it in for you the same way.

## Run it

```bash
cd frontend
pip install -r requirements.txt
cp .env.example .env      # edit if your services run on different hosts/ports
python run.py              # http://localhost:5000
```

Make sure both FastAPI services are already running (ports 8000 and 8001)
before you log in.

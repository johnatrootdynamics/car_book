# RaceTrack Flask Portal

Flask site for:
- Driver profiles and car profiles
- Track employee event creation
- Driver event signups

## Local run (no Docker)

### 1) Initialize MariaDB schema

```bash
mysql -u root < sql/init.sql
```

If needed for existing DBs:

```bash
mysql -u root srv-captain--carbookdb-db -e "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS layout_image_path VARCHAR(255) NULL;"
```

### 2) Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) Configure

```bash
cp .env.example .env
```

### 4) Run

```bash
export SESSION_COOKIE_SECURE=false # Local HTTP development only
python app.py
```

## Browser privacy

- The website uses essential session cookies for accounts, carts and protected forms. No analytics or advertising trackers are included.
- The notice writes only `trackops.cookie-notice.v1=dismissed` to tab-scoped `sessionStorage`, after dismissal. It never enables tracking. Footer links reopen the notice and work as ordinary `/cookies` links without JavaScript.
- Session cookies default to `Secure`, `HttpOnly` and `SameSite=Lax`, with no persistent expiry. Keep `SESSION_COOKIE_SECURE=true` (the default) on production HTTPS. Use `false` only for local HTTP development, including local Docker testing. Do not turn Flask sessions permanent to remember the notice.
- Marketing and policy pages enforce a same-origin content security policy. Fonts, video, Bootstrap Icons and the QR scanning library are self-hosted. The libraries retain their upstream licenses under `racetrack/static/vendor/`.
- Payments, waiver signing and social sign-in are separately requested provider services. Audit their behavior and any hosting/CDN-injected cookies in the deployed environment.
- Do not add analytics, pixels or optional browser storage behind the notice’s “Got it” action. New optional processing requires a separate assessment and controls before anything loads.
- Cookie controls do not establish overall legal compliance. The operator must confirm its actual data practices, service-provider arrangements, retention, state-law applicability and privacy-request handling with appropriate legal advice.

Privacy regression checks: `python -m unittest discover -s tests -p test_browser_privacy.py` and `node --test tests/test_cookie_notice.cjs`. The Python checks use an isolated SQLite database.

## Docker deployment

### Start services

```bash
docker compose up -d --build
```

- App runs on `http://localhost:8000`
- Webhook listener runs on `http://localhost:9000/github-webhook`

## GitHub webhook auto-deploy (on every push)

1) In your `.env`, set:

```env
WEBHOOK_SECRET=replace-with-random-secret
TARGET_BRANCH=main
```

2) In GitHub repo settings:
- **Payload URL**: `http://<your-server>:9000/github-webhook`
- **Content type**: `application/json`
- **Secret**: same as `WEBHOOK_SECRET`
- **Events**: Just the `push` event

3) On every push to `TARGET_BRANCH`, webhook service will:
- verify HMAC signature
- `git fetch` + hard reset to remote branch
- rebuild and restart `app` with `docker compose up -d --build app`

## Demo employee login
- Email: `employee@track.local`
- Password: `ChangeMe123!`

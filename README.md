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
python app.py
```

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

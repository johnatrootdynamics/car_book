# RaceTrack Flask Portal

Flask site for:
- Driver profiles and car profiles
- Track employee event creation
- Driver event signups

## 1) Create MariaDB database + tables

```bash
mysql -u root -p < sql/init.sql
```

If you already initialized the DB before this update, run:

```bash
mysql -u root -p racetrack -e "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS layout_image_path VARCHAR(255) NULL;"
```

If your DB user is not `racetrack`, update `.env`/environment to match.

## 2) Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3) Configure environment

```bash
cp .env.example .env
export $(grep -v '^#' .env | xargs)
```

Or set env vars manually:
- `SECRET_KEY`
- `DATABASE_URL`

## 4) Run app

```bash
python app.py
```

## Demo employee login
- Email: `employee@track.local`
- Password: `ChangeMe123!`

## Notes
- App expects schema from `sql/init.sql`.
- Driver accounts are self-registered in the UI.

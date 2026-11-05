# Expense Manager

A Django app for tracking balance, income and expenses per day, with user accounts.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000 and register an account.

## Environment variables (production)

| Variable        | Example                                 | Notes                                      |
|-----------------|-----------------------------------------|--------------------------------------------|
| `SECRET_KEY`    | long random string                      | Required when `DEBUG=False`                |
| `DEBUG`         | `False`                                 | Defaults to `True` (local dev)             |
| `ALLOWED_HOSTS` | `yourname.pythonanywhere.com`           | Comma-separated                            |
| `DATABASE_URL`  | `postgresql://user:pass@host/db`        | Optional; SQLite is used if not set        |

Generate a secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

---

## Option A: PythonAnywhere (recommended, free, keeps data in SQLite)

1. Sign up for a free "Beginner" account at https://www.pythonanywhere.com.
2. Optional, but it saves clicks: go to **Account**, then **API Token**, and click **Create a new API token**.
   This lets the script create and configure the web app for you.
3. Open **Consoles**, then **Bash**, and run:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/saranya13-tech/expense-manager/main/deploy/pythonanywhere.sh | bash
   ```
4. If you skipped the token, the script tells you which buttons to click on the **Web** tab. Do that, then run the command again.
5. Open `https://<username>.pythonanywhere.com` and register.

To deploy updates later, run the same command again. It pulls the latest code, migrates the database and reloads the site.
To get into `/admin`, run this in the console: `cd ~/expense-manager && DEBUG=False SECRET_KEY=$(cat ~/.expense_secret_key) ~/.virtualenvs/expense-venv/bin/python manage.py createsuperuser`

Note: free sites expire after about a month. Log in and click **Run until 1 month from today** on the Web tab before the expiry date shown there, or the site is switched off.

## Option B: Render + Neon Postgres (free, deploys on git push)

Render's free disk is wiped on every deploy and restart, so SQLite will **lose data** there.
Use a free Postgres database from https://neon.tech instead.

1. Create a Neon project and copy its connection string (`postgresql://...`).
2. Push this repo to GitHub.
3. In Render, choose **New**, then **Blueprint**, and pick the repo. It reads `render.yaml`.
4. When asked, paste the Neon string as `DATABASE_URL`. `SECRET_KEY` is generated for you.
5. Deploy. `build.sh` installs the dependencies, collects static files and runs migrations.

Note: Render's free web services go to sleep when idle, so the first visit after a while takes about 30 to 60 seconds.

## Tests

```bash
python manage.py test tracker
```

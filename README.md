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
2. Open a **Bash console** and get the code (push it to GitHub first, or upload a zip in the Files tab):
   ```bash
   git clone https://github.com/<you>/expense.git
   cd expense
   mkvirtualenv --python=python3.12 expense-venv
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py collectstatic --no-input
   python manage.py createsuperuser   # optional, for /admin
   ```
3. Go to the **Web** tab, then **Add a new web app**, then **Manual configuration**, then **Python 3.12**.
4. Under **Virtualenv**, enter `/home/<username>/.virtualenvs/expense-venv`.
5. Under **Static files**, add URL `/static/` and directory `/home/<username>/expense/staticfiles`.
6. Click the **WSGI configuration file** link and replace its contents with:
   ```python
   import os, sys

   path = '/home/<username>/expense'
   if path not in sys.path:
       sys.path.insert(0, path)

   os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
   os.environ['SECRET_KEY'] = '<paste-your-generated-secret-key>'
   os.environ['DEBUG'] = 'False'
   os.environ['ALLOWED_HOSTS'] = '<username>.pythonanywhere.com'

   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```
7. Turn on **Force HTTPS** on the Web tab, click **Reload**, and visit `https://<username>.pythonanywhere.com`.

To deploy updates: `git pull`, `python manage.py migrate`, `python manage.py collectstatic --no-input`, then click **Reload**.

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

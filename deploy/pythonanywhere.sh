#!/usr/bin/env bash
# One-shot setup / update for PythonAnywhere. Run inside a PythonAnywhere Bash console:
#   curl -fsSL https://raw.githubusercontent.com/saranya13-tech/expense-manager/main/deploy/pythonanywhere.sh | bash
# Safe to re-run: it pulls the latest code, migrates and reloads.
set -euo pipefail

REPO="https://github.com/saranya13-tech/expense-manager.git"
U="$(whoami)"
PA_HOST="${PYTHONANYWHERE_DOMAIN:-pythonanywhere.com}"   # pythonanywhere.com or eu.pythonanywhere.com
DOMAIN="$(echo "${U}.${PA_HOST}" | tr '[:upper:]' '[:lower:]')"   # PA domains are lowercase
APP="$HOME/expense-manager"
VENV="$HOME/.virtualenvs/expense-venv"
SECRET_FILE="$HOME/.expense_secret_key"
WSGI="/var/www/$(echo "$DOMAIN" | tr '.' '_')_wsgi.py"
API="https://www.${PA_HOST}/api/v0/user/${U}"

PY=""
for v in ${PY_VERSION:-} 3.12 3.13; do command -v "python$v" >/dev/null && { PY="python$v"; PYVER="${v/./}"; break; }; done
[ -n "$PY" ] || { echo "Need Python 3.12+ (Django 6). Update your system image in Account > System image."; exit 1; }
echo "==> Using $PY for $DOMAIN"

echo "==> Getting code"
if [ -d "$APP/.git" ]; then git -C "$APP" pull --ff-only; else git clone "$REPO" "$APP"; fi

echo "==> Virtualenv + dependencies"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --no-cache-dir --upgrade pip
"$VENV/bin/pip" install -q --no-cache-dir -r "$APP/requirements.txt"
# Packages only needed on Render (Postgres driver, gunicorn): remove them here to save disk space.
"$VENV/bin/pip" uninstall -q -y psycopg psycopg-binary gunicorn 2>/dev/null || true

[ -s "$SECRET_FILE" ] || { "$VENV/bin/python" -c "import secrets; print(secrets.token_urlsafe(50))" > "$SECRET_FILE"; chmod 600 "$SECRET_FILE"; }
export DJANGO_SETTINGS_MODULE=config.settings DEBUG=False ALLOWED_HOSTS="$DOMAIN" SECRET_KEY="$(cat "$SECRET_FILE")"

echo "==> Database + static files"
cd "$APP"
"$VENV/bin/python" manage.py migrate --no-input
"$VENV/bin/python" manage.py collectstatic --no-input -v0

api() { curl -fsS -H "Authorization: Token ${API_TOKEN}" "$@"; }
HAVE_API=0
if [ -n "${API_TOKEN:-}" ] && api "$API/webapps/" >/dev/null 2>&1; then HAVE_API=1; fi

if [ "$HAVE_API" = 1 ]; then
  if ! api "$API/webapps/$DOMAIN/" >/dev/null 2>&1; then
    echo "==> Creating web app $DOMAIN"
    api -X POST "$API/webapps/" -d "domain_name=$DOMAIN" -d "python_version=python$PYVER" >/dev/null
  fi
  api -X PATCH "$API/webapps/$DOMAIN/" -d "virtualenv_path=$VENV" -d "force_https=true" >/dev/null
fi

if [ ! -e "$WSGI" ]; then
  cat <<EOF

!! Web app not found. Do this once, then re-run this script:
   Web tab > "Add a new web app" > Next > "Manual configuration" > Python ${PY#python} > Next
   (Or create an API token under Account > API Token and re-run, and the script will do it for you.)
EOF
  exit 1
fi

echo "==> Writing $WSGI"
cat > "$WSGI" <<EOF
import os, sys

path = '$APP'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DEBUG'] = 'False'
os.environ['ALLOWED_HOSTS'] = '$DOMAIN'
os.environ['SECURE_SSL_REDIRECT'] = 'False'  # PythonAnywhere "Force HTTPS" handles this
with open('$SECRET_FILE') as f:
    os.environ['SECRET_KEY'] = f.read().strip()

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
EOF

if [ "$HAVE_API" = 1 ]; then
  echo "==> Reloading"
  api -X POST "$API/webapps/$DOMAIN/reload/" >/dev/null
  echo
  echo "DONE: https://$DOMAIN"
else
  cat <<EOF

Almost done. On the Web tab:
  1. Virtualenv:   $VENV
  2. Force HTTPS:  Enabled
  3. Click the green "Reload" button, then open https://$DOMAIN
EOF
fi

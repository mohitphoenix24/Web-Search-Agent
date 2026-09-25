#!/usr/bin/env bash
# One-time setup: Python packages, frontend packages and your Groq API key.
#
#   ./setup.sh      then      ./start.sh
#
set -euo pipefail
cd "$(dirname "$0")"

# Keep the .venv isolated: a PYTHONPATH set by ROS, conda etc. would leak
# other packages into it and can cause version clashes.
unset PYTHONPATH

step() { printf "\n\033[1;35m==>\033[0m \033[1m%s\033[0m\n" "$1"; }
ok()   { printf "    \033[32m✔\033[0m %s\n" "$1"; }
fail() { printf "    \033[31m✘ %s\033[0m\n" "$1"; exit 1; }

step "Checking what's installed"
command -v python3 >/dev/null || fail "Python 3.10 or newer is needed: https://www.python.org/downloads/"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || fail "Python 3.10 or newer is needed (you have $(python3 --version 2>&1))"
ok "$(python3 --version)"
command -v node >/dev/null && command -v npm >/dev/null || fail "Node.js 18 or newer is needed: https://nodejs.org"
node -e 'process.exit(parseInt(process.versions.node) < 18 ? 1 : 0)' \
  || fail "Node.js 18 or newer is needed (you have $(node --version))"
ok "Node $(node --version)"

step "Installing Python packages (into .venv)"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || fail "Couldn't create the virtual env. On Ubuntu/Debian run: sudo apt install python3-venv"
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
ok "Done"

step "Installing frontend packages (npm)"
(cd frontend && npm ci --no-audit --no-fund --loglevel=error)
ok "Done"

step "Groq API key (for the online models)"
if [ -n "${GROQ_API_KEY:-}" ]; then
  ok "Using GROQ_API_KEY from your environment"
elif grep -qs '^GROQ_API_KEY=gsk_' .env; then
  ok "Found in .env"
else
  echo "    Groq gives a free API key: https://console.groq.com/keys"
  read -rsp "    Paste your key here (it stays hidden): " key
  echo
  [ -n "$key" ] || fail "No key entered. Run ./setup.sh again once you have one."
  printf 'GROQ_API_KEY=%s\n' "$key" > .env
  chmod 600 .env
  ok "Saved in .env (git ignores this file, so it won't be pushed)"
fi

step "Testing the key with Groq"
.venv/bin/python - <<'PY' || fail "Key check failed (see above). Fix .env and run ./setup.sh again."
import openai
from llm import groq_client
try:
    groq_client.with_options(max_retries=1, timeout=15).models.list()
except openai.AuthenticationError:
    raise SystemExit("    Groq says this key is invalid.")
except openai.APIConnectionError:
    raise SystemExit("    Couldn't reach Groq. Check your internet connection.")
PY
ok "Key works"

printf "\n\033[1;32mAll set!\033[0m Start the app with \033[1m./start.sh\033[0m and open \033[1mhttp://localhost:5180\033[0m\n\n"

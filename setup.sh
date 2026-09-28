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

# --- API keys --------------------------------------------------------------
# has_key NAME PREFIX: is the key set, in the environment or in .env?
has_key() { [ -n "${!1:-}" ] || grep -qs "^$1=$2" .env; }

# save_key NAME VALUE: add (or replace) one line in .env, and never touch the
# other keys already in there. umask 077 keeps the file readable only by you.
save_key() {
  ( umask 077
    touch .env
    { grep -v "^$1=" .env || true; } > .env.tmp
    printf '%s=%s\n' "$1" "$2" >> .env.tmp
    mv .env.tmp .env )
}

# ask_key NAME "prompt": ask for a key (hidden), save it if one was given
ask_key() {
  read -rsp "    $2 " value
  echo
  if [ -n "$value" ]; then save_key "$1" "$value" && ok "Saved in .env (git ignores this file)"; else ok "Skipped"; fi
}

step "API keys for the online models"
echo "    You need at least one. OpenAI is paid and gives the best answers (the"
echo "    app only uses it when you pick an OpenAI model yourself);"
echo "    Groq has a free tier."
if has_key OPENAI_API_KEY sk-; then
  ok "OpenAI key found"
else
  echo "    OpenAI key: https://platform.openai.com/api-keys"
  ask_key OPENAI_API_KEY "Paste it (hidden), or press Enter to skip:"
fi
if has_key GROQ_API_KEY gsk_; then
  ok "Groq key found"
else
  echo "    Groq key (free): https://console.groq.com/keys"
  ask_key GROQ_API_KEY "Paste it (hidden), or press Enter to skip:"
fi
has_key OPENAI_API_KEY sk- || has_key GROQ_API_KEY gsk_ \
  || fail "You need at least one of the two keys. Run ./setup.sh again once you have one."

step "Tavily search key (optional)"
if has_key TAVILY_API_KEY tvly; then
  ok "Found — the agent will search with Tavily"
else
  echo "    Tavily is a search engine made for AI agents. It gives better"
  echo "    snippets than a plain web search, and the free tier is generous:"
  echo "    https://app.tavily.com"
  ask_key TAVILY_API_KEY "Paste a Tavily key, or press Enter to use DuckDuckGo:"
fi

step "Testing your keys"
.venv/bin/python - <<'PY' || fail "A key didn't work (see above). Fix it in .env and run ./setup.sh again."
import os, openai
from ai.llm import PROVIDERS, online_clients

failed = False
for name, client in online_clients.items():
    key = PROVIDERS[name]["key"]
    if not os.environ.get(key):
        continue
    label = PROVIDERS[name]["label"].split("· ")[1]
    try:
        client.with_options(max_retries=1, timeout=15).models.list()
        print(f"    \033[32m✔\033[0m {label} key works")
    except openai.AuthenticationError:
        print(f"    \033[31m✘ {label} says this key is invalid ({key})\033[0m")
        failed = True
    except openai.APIConnectionError:
        print(f"    \033[31m✘ Couldn't reach {label}. Check your internet connection.\033[0m")
        failed = True
raise SystemExit(1 if failed else 0)
PY

printf "\n\033[1;32mAll set!\033[0m Start the app with \033[1m./launch.sh\033[0m and open \033[1mhttp://localhost:5180\033[0m\n\n"

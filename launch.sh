#!/usr/bin/env bash
# Runs the app in the background. If it's already running, the old copy is
# stopped first, so only one copy ever runs.
#
#   ./launch.sh           start (or restart)  ->  http://localhost:5180
#   ./launch.sh stop      stop it
#   ./launch.sh status    is it running?
#   ./launch.sh logs      watch the logs (Ctrl+C stops watching, not the app)
#
# First time? Run ./setup.sh
set -uo pipefail
cd "$(dirname "$0")"

# Keep the .venv isolated (same reason as in setup.sh)
unset PYTHONPATH

APP_DIR="$(pwd -P)"
RUN=".run"  # pid files and logs (git-ignored)
BACKEND_PORT=8000
UI_PORT=5180

say()  { printf "\033[1;35m==>\033[0m \033[1m%s\033[0m\n" "$1"; }
ok()   { printf "    \033[32m✔\033[0m %s\n" "$1"; }
warn() { printf "    \033[33m!\033[0m %s\n" "$1"; }
fail() { printf "    \033[31m✘ %s\033[0m\n" "$1"; exit 1; }

alive()      { kill -0 "$1" 2>/dev/null; }
port_pids()  { lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null; }
port_open()  { (echo >"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
proc_cwd()   { lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p'; }

# A process is "ours" if it runs from inside this project folder.
# Anything else on our ports is left alone.
ours() {
  case "$(proc_cwd "$1")" in
    "$APP_DIR" | "$APP_DIR"/*) return 0 ;;
    *) return 1 ;;
  esac
}

stop_app() {
  local stopped=0

  # 1. The copy started by the last ./launch.sh. Each part runs in its own
  #    process group, so killing the group also stops its child processes.
  for name in backend frontend; do
    local file="$RUN/$name.pid"
    [ -f "$file" ] || continue
    local pid
    pid=$(cat "$file")
    if alive "$pid" && ours "$pid"; then
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
      stopped=1
    fi
    rm -f "$file"
  done

  # 2. Any other copy of this app still holding the ports (e.g. from ./start.sh)
  for port in $BACKEND_PORT $UI_PORT; do
    for pid in $(port_pids "$port"); do
      if ours "$pid"; then
        kill -TERM "$pid" 2>/dev/null
        stopped=1
      fi
    done
  done

  # Give them up to 5 seconds to exit, then force it
  for _ in $(seq 1 50); do
    port_open $BACKEND_PORT || port_open $UI_PORT || break
    sleep 0.1
  done
  for port in $BACKEND_PORT $UI_PORT; do
    for pid in $(port_pids "$port"); do
      ours "$pid" && kill -KILL "$pid" 2>/dev/null
    done
  done

  if [ "$stopped" = 1 ]; then ok "Stopped the running copy"; else ok "Nothing was running"; fi

  # Still taken? Then it's another program, which we don't touch.
  for port in $BACKEND_PORT $UI_PORT; do
    sleep 0.2
    if port_open "$port"; then
      local who
      who=$(port_pids "$port" | head -1)
      fail "Port $port is used by another program${who:+ (pid $who: $(ps -o comm= -p "$who"))}. It isn't part of this app, so I left it alone. Stop it and run ./launch.sh again."
    fi
  done
}

wait_until_ready() {  # name url pid log
  for _ in $(seq 1 60); do
    curl -sf -o /dev/null "$2" && return 0
    if ! alive "$3"; then
      echo
      tail -n 15 "$4" | sed 's/^/    | /'
      fail "The $1 crashed while starting. Full log: $4"
    fi
    sleep 0.5
  done
  fail "The $1 didn't start within 30 seconds. See $4"
}

start_app() {
  [ -x .venv/bin/uvicorn ] && [ -x frontend/node_modules/.bin/vite ] \
    || fail "Setup hasn't run yet. Run ./setup.sh first."
  if [ -z "${GROQ_API_KEY:-}" ] && ! grep -qs '^GROQ_API_KEY=.' .env; then
    warn "No GROQ_API_KEY in .env, so the online models will show as unavailable. Run ./setup.sh to add it."
  fi
  mkdir -p "$RUN"

  # set -m: every background job gets its own process group, so ./launch.sh stop
  # can end it together with its children. nohup: it keeps running after the
  # terminal is closed.
  set -m
  nohup .venv/bin/uvicorn server:app --port $BACKEND_PORT >"$RUN/backend.log" 2>&1 &
  echo $! >"$RUN/backend.pid"
  (cd frontend && exec nohup ./node_modules/.bin/vite >"../$RUN/frontend.log" 2>&1) &
  echo $! >"$RUN/frontend.pid"
  set +m

  wait_until_ready backend "http://127.0.0.1:$BACKEND_PORT/api/chats" "$(cat "$RUN/backend.pid")" "$RUN/backend.log"
  ok "Backend running on port $BACKEND_PORT"
  wait_until_ready frontend "http://localhost:$UI_PORT/" "$(cat "$RUN/frontend.pid")" "$RUN/frontend.log"
  ok "UI running on port $UI_PORT"

  printf "\n\033[1;32mReady:\033[0m open \033[1mhttp://localhost:%s\033[0m\n" "$UI_PORT"
  printf "It keeps running in the background. Logs: ./launch.sh logs   Stop: ./launch.sh stop\n\n"
}

show_status() {
  local running=0
  for name in backend frontend; do
    local pid=""
    [ -f "$RUN/$name.pid" ] && pid=$(cat "$RUN/$name.pid")
    if [ -n "$pid" ] && alive "$pid"; then
      ok "$name is running (pid $pid)"
      running=1
    else
      warn "$name is not running"
    fi
  done
  [ "$running" = 1 ] && printf "    Open http://localhost:%s\n" "$UI_PORT"
  return 0
}

case "${1:-start}" in
  start | restart)
    say "Stopping any copy that's already running"
    stop_app
    say "Starting the app"
    start_app
    ;;
  stop)
    say "Stopping the app"
    stop_app
    ;;
  status)
    show_status
    ;;
  logs)
    [ -f "$RUN/backend.log" ] || fail "No logs yet. Start the app with ./launch.sh"
    tail -n 30 -f "$RUN/backend.log" "$RUN/frontend.log"
    ;;
  *)
    echo "Usage: ./launch.sh [start|stop|status|logs]"
    exit 1
    ;;
esac

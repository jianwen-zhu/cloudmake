#!/bin/sh
set -eu

if [ "${CLOUDMAKE_TEST_LIVE_CODESPACES_NETWORK:-}" != 1 ]; then
	echo 'set CLOUDMAKE_TEST_LIVE_CODESPACES_NETWORK=1 to acknowledge live Codespaces use' >&2
	exit 2
fi
if [ "$#" -ne 1 ]; then
	echo 'usage: run.sh EVIDENCE_DIR' >&2
	exit 2
fi
: "${CODESPACE:?set CODESPACE to an existing temporary Cloudmake anchor Codespace}"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=$script_dir/project
cloudmake=${CLOUDMAKE_BIN:-$script_dir/../../../bin/cloudmake}
gh=${GH_BIN:-gh}
image=${CODESPACES_NETWORK_IMAGE:-docker.io/library/python@sha256:933b46a028fd786c9c3d426ebabc237e29a15912231ea8de576e95f0e4f41a4c}
remote_port=${CODESPACES_NETWORK_REMOTE_PORT:-18080}
evidence=$1
mkdir -p "$evidence"
evidence=$(CDPATH= cd -- "$evidence" && pwd)

case "$remote_port" in
	''|*[!0-9]*) echo 'CODESPACES_NETWORK_REMOTE_PORT must be numeric' >&2; exit 2 ;;
esac
if [ "$remote_port" -lt 1024 ] || [ "$remote_port" -gt 65535 ]; then
	echo 'CODESPACES_NETWORK_REMOTE_PORT must be between 1024 and 65535' >&2
	exit 2
fi

state_root=$evidence/local-state
mkdir -p "$state_root/config" "$state_root/state" "$state_root/cache"
export CLOUDMAKE_CONFIG_HOME=$state_root/config
export CLOUDMAKE_STATE_HOME=$state_root/state
export CLOUDMAKE_CACHE_HOME=$state_root/cache

token=cloudmake-inbound-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
forward_pid=
selected=

stop_forward() {
	if [ -n "$forward_pid" ]; then
		kill "$forward_pid" >/dev/null 2>&1 || :
		wait "$forward_pid" >/dev/null 2>&1 || :
		forward_pid=
	fi
}

cleanup() {
	stop_forward
	if [ -n "$selected" ]; then
		"$cloudmake" -C "$project" stop-server PORT="$remote_port" \
			>"$evidence/cleanup-server.log" 2>&1 || :
		"$cloudmake" -C "$project" --stop \
			>"$evidence/cleanup-resource.log" 2>&1 || :
	fi
}
trap cleanup EXIT HUP INT TERM

run_logged() {
	name=$1
	shift
	log=$evidence/$name.log
	status_file=$log.status
	(
		set +e
		PYTHONUNBUFFERED=1 "$@"
		command_status=$?
		printf '%s\n' "$command_status" >"$status_file"
		exit 0
	) 2>&1 | tee "$log"
	status=$(sed -n '1p' "$status_file")
	rm -f "$status_file"
	if [ -z "$status" ] || [ "$status" -ne 0 ]; then
		echo "Codespaces network acceptance stopped at $name; evidence was left intact." >&2
		exit "${status:-1}"
	fi
}

run_logged select "$cloudmake" -C "$project" --use codespaces --image "$image"
selected=1
run_logged serve "$cloudmake" -C "$project" serve \
	PORT="$remote_port" TOKEN="$token"

local_port=$(python3 -c \
	'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
"$gh" codespace ports forward "$remote_port:$local_port" -c "$CODESPACE" \
	>"$evidence/forward.log" 2>&1 &
forward_pid=$!

attempt=0
while :; do
	attempt=$((attempt + 1))
	if python3 - "$local_port" "$token" <<'PY'
import sys
import urllib.request

port = int(sys.argv[1])
expected = sys.argv[2]
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
        actual = response.read().decode("utf-8").strip()
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if actual == expected else 1)
PY
	then
		break
	fi
	if ! kill -0 "$forward_pid" >/dev/null 2>&1; then
		echo 'Codespaces port-forward process exited before the workload was reachable' >&2
		exit 1
	fi
	if [ "$attempt" -ge 30 ]; then
		echo 'Codespaces workload did not become reachable through the inbound tunnel' >&2
		exit 1
	fi
	sleep 1
done

printf '%s\n' \
	"codespace=$CODESPACE" \
	"remote_port=$remote_port" \
	"local_port=$local_port" \
	"visibility=authenticated-private" \
	"attempts=$attempt" \
	"result=passed" >"$evidence/inbound-result.txt"
printf '[cloudmake] Codespaces inbound forwarding passed port=%s visibility=authenticated-private\n' \
	"$remote_port"

stop_forward
run_logged stop-server "$cloudmake" -C "$project" stop-server PORT="$remote_port"
run_logged stop-resource "$cloudmake" -C "$project" --stop
selected=
trap - EXIT HUP INT TERM

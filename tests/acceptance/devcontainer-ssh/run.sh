#!/bin/sh
set -eu

if [ "${CLOUDMAKE_TEST_LIVE_DEVCONTAINER_SSH:-}" != 1 ]; then
	echo 'set CLOUDMAKE_TEST_LIVE_DEVCONTAINER_SSH=1 to acknowledge live SSH use' >&2
	exit 2
fi
if [ "$#" -ne 1 ]; then
	echo 'usage: run.sh EVIDENCE_DIR' >&2
	exit 2
fi
: "${SSH_HOST:?set SSH_HOST to an existing OpenSSH alias}"
: "${CLOUDMAKE_DEVCONTAINER_IMAGE:?set a digest-pinned image containing make and python3}"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cloudmake=${CLOUDMAKE_BIN:-$script_dir/../../../bin/cloudmake}
evidence=$1
mkdir -p "$evidence"
evidence=$(CDPATH= cd -- "$evidence" && pwd)
temporary=$(mktemp -d "${TMPDIR:-/tmp}/cloudmake-devcontainer-ssh.XXXXXX")
project=$temporary/project
cp -R "$script_dir/project" "$project"
mkdir -p "$project/.devcontainer"

port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
python3 - "$project/.devcontainer/devcontainer.json" "$CLOUDMAKE_DEVCONTAINER_IMAGE" "$port" <<'PY'
import json
from pathlib import Path
import sys

Path(sys.argv[1]).write_text(json.dumps({
    "image": sys.argv[2],
    "remoteEnv": {"CLOUDMAKE_PROFILE": "portable"},
    "hostRequirements": {"cpus": 1},
    "forwardPorts": [int(sys.argv[3])],
}, indent=2) + "\n", encoding="utf-8")
PY

export CLOUDMAKE_CONFIG_HOME=$temporary/config
export CLOUDMAKE_STATE_HOME=$temporary/state
export CLOUDMAKE_CACHE_HOME=$temporary/cache
token=cloudmake-devcontainer-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')

cleanup() {
	rm -rf "$temporary"
}
trap cleanup EXIT HUP INT TERM

run_logged() {
	name=$1
	shift
	status=0
	output=$("$@" 2>&1) || status=$?
	printf '%s\n' "$output" | tee "$evidence/$name.log"
	return "$status"
}

run_logged select "$cloudmake" -C "$project" --use ssh --host "$SSH_HOST" --devcontainer
run_logged verify "$cloudmake" -C "$project" verify
run_logged increment-one "$cloudmake" -C "$project" increment
run_logged increment-two "$cloudmake" -C "$project" increment
grep 'workstation count=1' "$evidence/increment-one.log" >/dev/null
grep 'workstation count=2' "$evidence/increment-two.log" >/dev/null

set +e
"$cloudmake" -C "$project" serve PORT="$port" TOKEN="$token" \
	>"$evidence/serve.log" 2>&1 &
serve_pid=$!
set -e
attempt=0
while :; do
	attempt=$((attempt + 1))
	if response=$(curl -fsS --max-time 2 "http://127.0.0.1:$port/"); then
		test "$response" = "$token"
		break
	fi
	if ! kill -0 "$serve_pid" >/dev/null 2>&1; then
		wait "$serve_pid"
		echo 'foreground Dev Container target exited before its tunnel was reachable' >&2
		exit 1
	fi
	if [ "$attempt" -ge 30 ]; then
		echo 'Dev Container loopback tunnel did not become reachable' >&2
		exit 1
	fi
	sleep 1
done
wait "$serve_pid"
cat "$evidence/serve.log"

run_logged collect "$cloudmake" -C "$project" --collect dist export-artifact
test -f "$project/artifacts/result.txt"
grep 'devcontainer-ssh-ok' "$project/artifacts/result.txt" >/dev/null
if [ -n "${CLOUDMAKE_EXPECT_RUNTIME:-}" ]; then
	grep "runner=oci runtime=$CLOUDMAKE_EXPECT_RUNTIME" "$evidence/verify.log" >/dev/null
fi

printf '%s\n' \
	"host=$SSH_HOST" \
	"port=$port" \
	"runtime=${CLOUDMAKE_EXPECT_RUNTIME:-dynamically-qualified}" \
	"result=passed" >"$evidence/result.txt"
trap - EXIT HUP INT TERM
cleanup
printf 'Portable Dev Container SSH acceptance passed.\n'

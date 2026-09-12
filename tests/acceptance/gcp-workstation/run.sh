#!/bin/sh
set -eu

if [ "${CLOUDMAKE_TEST_LIVE_GCP:-}" != 1 ]; then
	echo 'set CLOUDMAKE_TEST_LIVE_GCP=1 to acknowledge live Google Cloud use' >&2
	exit 2
fi
if [ "$#" -ne 1 ]; then
	echo 'usage: run.sh EVIDENCE_DIR' >&2
	exit 2
fi
: "${GCP_PROJECT:?set GCP_PROJECT to the existing Google Cloud project}"
: "${GCP_ZONE:?set GCP_ZONE to the existing VM zone}"
: "${GCP_INSTANCE:?set GCP_INSTANCE to the existing VM name}"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=$script_dir/project
cloudmake=${CLOUDMAKE_BIN:-$script_dir/../../../bin/cloudmake}
gate=${GCP_GATE:-cpu}
evidence=$1
mkdir -p "$evidence"
evidence=$(CDPATH= cd -- "$evidence" && pwd)

case "$gate" in
	cpu|g4) ;;
	*) echo 'GCP_GATE must be cpu or g4' >&2; exit 2 ;;
esac

state_root=$evidence/local-state
mkdir -p "$state_root/config" "$state_root/state" "$state_root/cache"
export CLOUDMAKE_CONFIG_HOME=$state_root/config
export CLOUDMAKE_STATE_HOME=$state_root/state
export CLOUDMAKE_CACHE_HOME=$state_root/cache

selected=
target_pid=
gcloud_bin=${GCLOUD_BIN:-gcloud}
cleanup() {
	if [ -n "$target_pid" ]; then
		kill "$target_pid" >/dev/null 2>&1 || :
		wait "$target_pid" >/dev/null 2>&1 || :
	fi
	if [ -n "$selected" ]; then
		if ! "$cloudmake" -C "$project" --stop >"$evidence/cleanup-stop.log" 2>&1; then
			echo 'cloudmake stop failed; using the provider CLI as a billing-safe fallback' >>"$evidence/cleanup-stop.log"
			"$gcloud_bin" compute instances stop "$GCP_INSTANCE" \
				--project "$GCP_PROJECT" --zone "$GCP_ZONE" --quiet \
				>>"$evidence/cleanup-stop.log" 2>&1 || :
		fi
	fi
}
trap cleanup EXIT HUP INT TERM

run_logged() {
	name=$1
	shift
	if "$@" >"$evidence/$name.log" 2>&1; then
		cat "$evidence/$name.log"
	else
		status=$?
		cat "$evidence/$name.log" >&2
		return "$status"
	fi
}

if [ "$gate" = cpu ]; then
	run_logged select "$cloudmake" -C "$project" --use gcp --persist --devcontainer
else
	: "${GCP_G4_IMAGE:?set GCP_G4_IMAGE to a digest-pinned CUDA OCI image containing make}"
	gpu_device=${GCP_G4_CDI_DEVICE:-nvidia.com/gpu=all}
	run_logged select "$cloudmake" -C "$project" --use gcp --persist \
		--image "$GCP_G4_IMAGE" --device "$gpu_device"
fi
selected=1

run_logged environment "$cloudmake" -C "$project" --environment
run_logged increment-1 "$cloudmake" -C "$project" increment
first_count=$(sed -n 's/^persistent-count=//p' "$evidence/increment-1.log" | tail -n 1)
case "$first_count" in
	''|*[!0-9]*) echo 'first persistent counter was not observed' >&2; exit 1 ;;
esac
run_logged increment-2 "$cloudmake" -C "$project" increment
second_count=$(sed -n 's/^persistent-count=//p' "$evidence/increment-2.log" | tail -n 1)
case "$second_count" in
	''|*[!0-9]*) echo 'second persistent counter was not observed' >&2; exit 1 ;;
esac
test "$second_count" -eq $((first_count + 1))

if [ "$gate" = cpu ]; then
	run_logged outbound "$cloudmake" -C "$project" outbound
	"$cloudmake" -C "$project" serve-once >"$evidence/serve.log" 2>&1 &
	target_pid=$!
	attempt=0
	while :; do
		attempt=$((attempt + 1))
		if python3 - <<'PY'
import urllib.request
try:
    body = urllib.request.urlopen("http://127.0.0.1:18080/", timeout=2).read()
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if body == b"cloudmake-gcp-inbound\n" else 1)
PY
		then
			break
		fi
		if ! kill -0 "$target_pid" >/dev/null 2>&1; then
			cat "$evidence/serve.log" >&2
			echo 'GCP foreground target exited before its loopback tunnel was reachable' >&2
			exit 1
		fi
		if [ "$attempt" -ge "${GCP_FORWARD_WAIT_SECONDS:-180}" ]; then
			echo 'GCP loopback-forwarded workload did not become reachable' >&2
			exit 1
		fi
		sleep 1
	done
	wait "$target_pid"
	target_pid=
	printf 'result=passed\nattempts=%s\n' "$attempt" >"$evidence/inbound-result.txt"
else
	run_logged gpu-smoke "$cloudmake" -C "$project" gpu-smoke
fi

run_logged stop-midpoint "$cloudmake" -C "$project" --stop
run_logged verify-after-restart "$cloudmake" -C "$project" verify
grep 'resource=started' "$evidence/verify-after-restart.log" >/dev/null
grep "persistent-count=$second_count" "$evidence/verify-after-restart.log" >/dev/null
run_logged collect "$cloudmake" -C "$project" --collect dist export-artifact
test "$(cat "$project/.cloudmake/artifacts/count.txt")" = "$second_count"
run_logged stop-final "$cloudmake" -C "$project" --stop
selected=
trap - EXIT HUP INT TERM

printf 'GCP %s remote-workstation acceptance passed; disk retained.\n' "$gate"

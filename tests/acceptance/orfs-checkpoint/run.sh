#!/bin/sh
set -eu

if [ "${CLOUDMAKE_TEST_LIVE_ORFS_CHECKPOINT:-}" != 1 ]; then
	echo 'set CLOUDMAKE_TEST_LIVE_ORFS_CHECKPOINT=1 to acknowledge live Colab use' >&2
	exit 2
fi
if [ "$#" -ne 4 ]; then
	echo 'usage: run.sh PROJECT STAGE1_TARGET STAGE2_TARGET COLLECT_DIR' >&2
	exit 2
fi
if [ -z "${COLAB_SESSION:-}" ]; then
	echo 'COLAB_SESSION must name a dedicated acceptance session' >&2
	exit 2
fi

project=$1
stage1=$2
stage2=$3
collect_dir=$4
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cloudmake=${CLOUDMAKE_BIN:-$script_dir/../../../bin/cloudmake}
log_dir=${CLOUDMAKE_ACCEPTANCE_LOG_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/cloudmake-orfs.XXXXXX")}
mkdir -p "$log_dir"

run_logged() {
	name=$1
	shift
	log=$log_dir/$name.log
	status_file=$log.status
	rm -f "$status_file"
	(
		set +e
		PYTHONUNBUFFERED=1 "$@"
		command_status=$?
		printf '%s\n' "$command_status" >"$status_file"
		exit 0
	) 2>&1 | tee "$log"
	if [ ! -s "$status_file" ]; then
		echo "ORFS acceptance could not determine command status; session $COLAB_SESSION was left intact." >&2
		exit 1
	fi
	status=$(sed -n '1p' "$status_file")
	rm -f "$status_file"
	if [ "$status" -ne 0 ]; then
		echo "ORFS acceptance stopped; session $COLAB_SESSION was left intact for inspection." >&2
		exit "$status"
	fi
}

run_logged select "$cloudmake" -C "$project" --use colab --persist
run_logged stage1 "$cloudmake" -C "$project" "$stage1"
grep -q 'persistent-workspace snapshot-published=' "$log_dir/stage1.log"

# A successful target is an unambiguous checkpoint boundary. Destroying the VM
# here is the behavior under test, not cleanup after an unknown target state.
run_logged stop-after-stage1 "$cloudmake" -C "$project" --stop

run_logged stage2 "$cloudmake" -C "$project" --collect "$collect_dir" "$stage2"
grep -q 'persistent-workspace snapshot-restored=' "$log_dir/stage2.log"
grep -q 'persistent-workspace snapshot-published=' "$log_dir/stage2.log"
run_logged stop-after-stage2 "$cloudmake" -C "$project" --stop

printf '[cloudmake] ORFS checkpoint acceptance passed logs=%s\n' "$log_dir"

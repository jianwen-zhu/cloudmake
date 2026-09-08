#!/bin/sh
set -eu

if [ "${CLOUDMAKE_TEST_LIVE_ORFS_OCI:-}" != 1 ]; then
	echo 'set CLOUDMAKE_TEST_LIVE_ORFS_OCI=1 to acknowledge live Colab and registry use' >&2
	exit 2
fi
if [ "$#" -ne 2 ]; then
	echo 'usage: run.sh PROJECT COLLECT_DIR' >&2
	exit 2
fi
if [ -z "${COLAB_SESSION:-}" ]; then
	echo 'COLAB_SESSION must name a dedicated acceptance session' >&2
	exit 2
fi

project=$1
collect_dir=$2
image='docker.io/openroad/orfs@sha256:cdb377cec7796c5cb01d482ca035811bfe559ca55dcca7f5e5f46fa811c63142'
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cloudmake=${CLOUDMAKE_BIN:-$script_dir/../../../bin/cloudmake}
log_dir=${CLOUDMAKE_ACCEPTANCE_LOG_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/cloudmake-orfs-oci.XXXXXX")}
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
		echo "ORFS OCI acceptance could not determine status; session $COLAB_SESSION was left intact." >&2
		exit 1
	fi
	status=$(sed -n '1p' "$status_file")
	rm -f "$status_file"
	if [ "$status" -ne 0 ]; then
		echo "ORFS OCI acceptance stopped; session $COLAB_SESSION was left intact for inspection." >&2
		exit "$status"
	fi
}

run_logged select "$cloudmake" -C "$project" --use colab --gpu=T4 \
	--image "$image" --device nvidia.com/gpu=all
run_logged toolcheck "$cloudmake" -C "$project" orfs-toolcheck
run_logged enable-persistence "$cloudmake" -C "$project" --persist --start
run_logged stage1 "$cloudmake" -C "$project" orfs-floorplan
grep -q 'persistent-workspace snapshot-published=' "$log_dir/stage1.log"

# Stage 1 is confirmed and checkpointed, so deliberately replace the VM.
run_logged stop-after-stage1 "$cloudmake" -C "$project" --stop
run_logged stage2 "$cloudmake" -C "$project" --collect "$collect_dir" orfs-place
grep -q 'persistent-workspace snapshot-restored=' "$log_dir/stage2.log"
grep -q 'persistent-workspace snapshot-published=' "$log_dir/stage2.log"
run_logged stop-after-stage2 "$cloudmake" -C "$project" --stop

printf '[cloudmake] ORFS OCI acceptance passed logs=%s\n' "$log_dir"

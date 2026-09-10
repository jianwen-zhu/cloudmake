#!/bin/sh
set -eu

if [ "${CLOUDMAKE_TEST_LIVE_CODESPACES_COURSES:-}" != 1 ]; then
	echo 'set CLOUDMAKE_TEST_LIVE_CODESPACES_COURSES=1 to acknowledge live Codespaces use' >&2
	exit 2
fi
if [ "$#" -ne 4 ]; then
	echo 'usage: run.sh ECE326_LAB1 ECE326_LAB4 ECE467_PROJECT EVIDENCE_DIR' >&2
	exit 2
fi
: "${CODESPACE:?set CODESPACE to an existing temporary Cloudmake anchor Codespace}"

lab1=$1
lab4=$2
ece467=$3
evidence=$4
for project in "$lab1" "$lab4" "$ece467"; do
	test -f "$project/Makefile" || {
		echo "acceptance project has no Makefile: $project" >&2
		exit 2
	}
done

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cloudmake=${CLOUDMAKE_BIN:-$script_dir/../../../bin/cloudmake}
course_image=${CODESPACES_COURSE_IMAGE:-docker.io/library/python@sha256:933b46a028fd786c9c3d426ebabc237e29a15912231ea8de576e95f0e4f41a4c}
mkdir -p "$evidence"
evidence=$(CDPATH= cd -- "$evidence" && pwd)
state_root=$evidence/local-state
mkdir -p "$state_root/config" "$state_root/state" "$state_root/cache"
export CLOUDMAKE_CONFIG_HOME=$state_root/config
export CLOUDMAKE_STATE_HOME=$state_root/state
export CLOUDMAKE_CACHE_HOME=$state_root/cache

stop_resource() {
	"$cloudmake" -C "$lab1" --stop >/dev/null 2>&1 || :
}
trap stop_resource EXIT HUP INT TERM

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
		echo "Codespaces course acceptance stopped at $name; evidence was left intact." >&2
		exit "${status:-1}"
	fi
}

run_logged ece326-lab1-select "$cloudmake" -C "$lab1" --use codespaces \
	--image "$course_image"
run_logged ece326-lab1-setup "$cloudmake" -C "$lab1" setup
run_logged ece326-lab1-test "$cloudmake" -C "$lab1" test
run_logged ece326-lab1-benchmark "$cloudmake" -C "$lab1" \
	benchmark MODEL=stories260K

run_logged ece326-lab4-select "$cloudmake" -C "$lab4" --use codespaces \
	--image "$course_image"
run_logged ece326-lab4-paired "$cloudmake" -C "$lab4" \
	leaderboard-pair-ready CANDIDATE_LABEL=codespaces-gate

run_logged ece467-select "$cloudmake" -C "$ece467" --use codespaces \
	--image "$course_image"
for target in project-check lab-axpy-01-cpu lab-gemm-01-cpu llmc-test; do
	run_logged "ece467-$target" "$cloudmake" -C "$ece467" "$target"
done

stop_resource
trap - EXIT HUP INT TERM
printf '[cloudmake] Codespaces ECE326/ECE467 CPU acceptance passed evidence=%s\n' "$evidence"

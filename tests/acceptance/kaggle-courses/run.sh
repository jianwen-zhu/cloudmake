#!/bin/sh
set -eu

if [ "${CLOUDMAKE_TEST_LIVE_KAGGLE_COURSES:-}" != 1 ]; then
	echo 'set CLOUDMAKE_TEST_LIVE_KAGGLE_COURSES=1 to acknowledge live Kaggle use' >&2
	exit 2
fi
if [ "$#" -ne 4 ]; then
	echo 'usage: run.sh ECE326_LAB1 ECE326_LAB4 ECE467_PROJECT EVIDENCE_DIR' >&2
	exit 2
fi
if [ -z "${KAGGLE_USERNAME:-}" ]; then
	echo 'KAGGLE_USERNAME must name the authenticated Kaggle account' >&2
	exit 2
fi

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
accelerator=${KAGGLE_COURSE_ACCELERATOR:-NvidiaTeslaT4}
mkdir -p "$evidence"
evidence=$(CDPATH= cd -- "$evidence" && pwd)
state_root=$evidence/local-state
mkdir -p "$state_root/config" "$state_root/state" "$state_root/cache"
export CLOUDMAKE_CONFIG_HOME=$state_root/config
export CLOUDMAKE_STATE_HOME=$state_root/state
export CLOUDMAKE_CACHE_HOME=$state_root/cache
export KAGGLE_ENABLE_INTERNET=${KAGGLE_ENABLE_INTERNET:-true}
export KAGGLE_TIMEOUT=${KAGGLE_TIMEOUT:-7200}

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
		echo "Kaggle course acceptance stopped at $name; private evidence was left intact." >&2
		exit "${status:-1}"
	fi
}

# ECE326: reproduce the clean public Lab 1 and paired Lab 4 gates used for the
# accepted Colab release, with every command executed in a fresh Kaggle VM.
run_logged ece326-lab1-select "$cloudmake" -C "$lab1" --use kaggle --cpu --persist
run_logged ece326-lab1-setup "$cloudmake" -C "$lab1" setup
run_logged ece326-lab1-test "$cloudmake" -C "$lab1" test
run_logged ece326-lab1-benchmark "$cloudmake" -C "$lab1" \
	--collect reports benchmark MODEL=stories260K
run_logged ece326-lab4-select "$cloudmake" -C "$lab4" --use kaggle --cpu --persist
run_logged ece326-lab4-paired "$cloudmake" -C "$lab4" \
	--collect reports leaderboard-pair-ready CANDIDATE_LABEL=kaggle-gate

# ECE467: reproduce the published end-to-end Colab onboarding sequence. Each
# target receives a fresh T4 VM and must recover the same checkpointed home.
run_logged ece467-select "$cloudmake" -C "$ece467" --use kaggle \
	--gpu="$accelerator" --persist
for target in \
	bootstrap ttl-prelabs verify \
	lab-axpy-01-cpu lab-axpy-02-device lab-axpy-03-tilelang \
	lab-gemm-01-cpu lab-gemm-02-device lab-gemm-03-tilelang lab-gemm-04-watch
do
	run_logged "ece467-$target" "$cloudmake" -C "$ece467" "$target"
done

printf '[cloudmake] Kaggle ECE326/ECE467 acceptance passed evidence=%s\n' "$evidence"

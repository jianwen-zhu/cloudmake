#!/bin/sh
set -eu

ORFS_IMAGE='docker.io/openroad/orfs@sha256:cdb377cec7796c5cb01d482ca035811bfe559ca55dcca7f5e5f46fa811c63142'
flow=/OpenROAD-flow-scripts/flow
state=$PWD/.orfs-state
result=$state/results/nangate45/gcd/base
floorplan=$result/2_floorplan.odb
place=$result/3_place.odb
acceptance=$state/acceptance

die() {
	printf '[orfs-oci] %s\n' "$*" >&2
	exit 1
}

run_orfs() {
	target=$1
	printf '[orfs-oci] running target=%s design=nangate45/gcd\n' "$target"
	make -C "$flow" -j1 \
		FLOW_HOME="$flow/" \
		WORK_HOME="$state" \
		YOSYS_EXE=/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys \
		OPENROAD_EXE=/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad \
		KLAYOUT_CMD=/usr/bin/klayout \
		DESIGN_CONFIG=./designs/nangate45/gcd/config.mk \
		"$target"
}

record_floorplan() {
	test -s "$floorplan" || die "ORFS did not produce $floorplan"
	mkdir -p "$acceptance"
	sha256sum "$floorplan" | awk '{print $1}' >"$acceptance/floorplan.sha256"
	stat -c '%Y' "$floorplan" >"$acceptance/floorplan.mtime"
	printf '%s\n' "$ORFS_IMAGE" >"$acceptance/orfs.image"
	printf '[orfs-oci] recorded floorplan sha256=%s\n' "$(cat "$acceptance/floorplan.sha256")"
}

verify_floorplan() {
	test -s "$floorplan" || die 'restored floorplan database is absent'
	test -s "$acceptance/floorplan.sha256" || die 'restored floorplan checksum is absent'
	test -s "$acceptance/floorplan.mtime" || die 'restored floorplan timestamp is absent'
	actual=$(sha256sum "$floorplan" | awk '{print $1}')
	expected=$(cat "$acceptance/floorplan.sha256")
	[ "$actual" = "$expected" ] || die 'restored floorplan checksum does not match stage 1'
}

case "${1:-}" in
	toolcheck)
		test -x /OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad || die 'OpenROAD executable is absent'
		test -x /OpenROAD-flow-scripts/tools/install/yosys/bin/yosys || die 'Yosys executable is absent'
		/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad -version
		/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys -V
		nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
		;;
	floorplan)
		run_orfs floorplan
		record_floorplan
		;;
	place)
		verify_floorplan
		run_orfs place
		verify_floorplan
		test -s "$place" || die "ORFS did not produce $place"
		after_mtime=$(stat -c '%Y' "$floorplan")
		expected_mtime=$(cat "$acceptance/floorplan.mtime")
		[ "$after_mtime" = "$expected_mtime" ] || die 'ORFS regenerated the restored floorplan'
		mkdir -p evidence
		{
			printf 'orfs_image=%s\n' "$(cat "$acceptance/orfs.image")"
			printf 'floorplan_sha256=%s\n' "$(cat "$acceptance/floorplan.sha256")"
			printf 'floorplan_mtime=%s\n' "$after_mtime"
			printf 'place_sha256=%s\n' "$(sha256sum "$place" | awk '{print $1}')"
			printf 'stage2_reused_floorplan=yes\n'
		} >evidence/orfs-oci.txt
		printf '[orfs-oci] evidence=%s/evidence/orfs-oci.txt\n' "$PWD"
		;;
	*)
		die 'usage: orfs-oci.sh {toolcheck|floorplan|place}'
		;;
esac

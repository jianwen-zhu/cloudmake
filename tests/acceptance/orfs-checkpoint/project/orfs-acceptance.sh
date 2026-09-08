#!/bin/sh
set -eu

ORFS_COMMIT=68cc9bc974502b4786a68e9f51a092e0fcb56e82
ORFS_IMAGE=openroad/orfs:26Q3-488-g68cc9bc97
APPTAINER_VERSION=1.5.3

state=.orfs-state
orfs=$state/orfs
apptainer_home=$state/apptainer
apptainer=$apptainer_home/bin/apptainer
image=$state/openroad-orfs.sif
acceptance=$state/acceptance
result=$orfs/results/nangate45/gcd/base
floorplan=$result/2_floorplan.odb
place=$result/3_place.odb

die() {
	printf '[orfs-acceptance] %s\n' "$*" >&2
	exit 1
}

provision_apptainer() {
	if [ -x "$apptainer" ]; then
		return
	fi
	printf '[orfs-acceptance] installing project-local Apptainer %s\n' "$APPTAINER_VERSION"
	if ! command -v rpm2cpio >/dev/null 2>&1 || ! command -v cpio >/dev/null 2>&1; then
		apt-get update -qq
		DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rpm2cpio cpio
	fi
	mkdir -p "$state"
	installer=$state/install-apptainer.sh
	curl -fsSL \
		"https://raw.githubusercontent.com/apptainer/apptainer/v$APPTAINER_VERSION/tools/install-unprivileged.sh" \
		-o "$installer"
	bash "$installer" -v "$APPTAINER_VERSION" "$apptainer_home"
	rm -f "$installer"
	test -x "$apptainer" || die 'Apptainer installation did not produce an executable'
}

provision_orfs() {
	if [ -d "$orfs/.git" ]; then
		actual=$(git -C "$orfs" rev-parse HEAD)
		[ "$actual" = "$ORFS_COMMIT" ] || die "restored ORFS revision $actual does not match $ORFS_COMMIT"
		return
	fi
	printf '[orfs-acceptance] acquiring ORFS source %s\n' "$ORFS_COMMIT"
	mkdir -p "$orfs"
	git -C "$orfs" init -q
	git -C "$orfs" remote add origin https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git
	git -C "$orfs" fetch -q --depth=1 origin "$ORFS_COMMIT"
	git -C "$orfs" checkout -q --detach FETCH_HEAD
	actual=$(git -C "$orfs" rev-parse HEAD)
	[ "$actual" = "$ORFS_COMMIT" ] || die "downloaded ORFS revision $actual does not match $ORFS_COMMIT"
}

provision_image() {
	if [ -s "$image" ]; then
		return
	fi
	printf '[orfs-acceptance] acquiring OCI image docker://%s\n' "$ORFS_IMAGE"
	mkdir -p "$state/apptainer-cache" "$state/apptainer-tmp"
	APPTAINER_CACHEDIR=$PWD/$state/apptainer-cache \
	APPTAINER_TMPDIR=$PWD/$state/apptainer-tmp \
		"$apptainer" pull --force "$image" "docker://$ORFS_IMAGE"
	test -s "$image" || die 'OCI image acquisition did not produce a SIF file'
	# The SIF is the project-owned runnable bundle. Do not checkpoint duplicate
	# OCI layer and conversion caches after a successful pull.
	rm -rf "$state/apptainer-cache" "$state/apptainer-tmp"
}

provision() {
	provision_apptainer
	provision_orfs
	provision_image
}

run_orfs() {
	target=$1
	printf '[orfs-acceptance] running ORFS target=%s design=nangate45/gcd\n' "$target"
	"$apptainer" exec --userns --bind "$PWD/$orfs:/work" --pwd /work/flow "$image" \
		env \
		FLOW_HOME=/OpenROAD-flow-scripts/flow/ \
		WORK_HOME=/work \
		YOSYS_EXE=/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys \
		OPENROAD_EXE=/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad \
		KLAYOUT_CMD=/usr/bin/klayout \
		make DESIGN_CONFIG=./designs/nangate45/gcd/config.mk "$target"
}

record_floorplan() {
	test -s "$floorplan" || die "ORFS did not produce $floorplan"
	mkdir -p "$acceptance"
	sha256sum "$floorplan" | awk '{print $1}' > "$acceptance/floorplan.sha256"
	stat -c '%Y' "$floorplan" > "$acceptance/floorplan.mtime"
	printf '%s\n' "$ORFS_COMMIT" > "$acceptance/orfs.commit"
	printf '%s\n' "$ORFS_IMAGE" > "$acceptance/orfs.image"
	printf '[orfs-acceptance] recorded floorplan sha256=%s\n' "$(cat "$acceptance/floorplan.sha256")"
}

verify_floorplan() {
	test -s "$floorplan" || die 'restored floorplan database is absent'
	test -s "$acceptance/floorplan.sha256" || die 'restored floorplan checksum is absent'
	test -s "$acceptance/floorplan.mtime" || die 'restored floorplan timestamp is absent'
	actual=$(sha256sum "$floorplan" | awk '{print $1}')
	expected=$(cat "$acceptance/floorplan.sha256")
	[ "$actual" = "$expected" ] || die 'restored floorplan checksum does not match stage 1'
	printf '[orfs-acceptance] verified restored floorplan sha256=%s\n' "$actual"
}

write_evidence() {
	test -s "$place" || die "ORFS did not produce $place"
	verify_floorplan
	after_mtime=$(stat -c '%Y' "$floorplan")
	expected_mtime=$(cat "$acceptance/floorplan.mtime")
	[ "$after_mtime" = "$expected_mtime" ] || die 'ORFS regenerated the restored floorplan during stage 2'
	mkdir -p evidence
	{
		printf 'orfs_commit=%s\n' "$(cat "$acceptance/orfs.commit")"
		printf 'orfs_image=%s\n' "$(cat "$acceptance/orfs.image")"
		printf 'floorplan_sha256=%s\n' "$(cat "$acceptance/floorplan.sha256")"
		printf 'floorplan_mtime=%s\n' "$after_mtime"
		printf 'place_sha256=%s\n' "$(sha256sum "$place" | awk '{print $1}')"
		printf 'stage2_reused_floorplan=yes\n'
	} > evidence/orfs-checkpoint.txt
	printf '[orfs-acceptance] evidence=%s/evidence/orfs-checkpoint.txt\n' "$PWD"
}

case "${1:-}" in
	floorplan)
		provision
		run_orfs floorplan
		record_floorplan
		;;
	place)
		provision
		verify_floorplan
		run_orfs place
		write_evidence
		;;
	*)
		die 'usage: orfs-acceptance.sh {floorplan|place}'
		;;
esac

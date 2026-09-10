#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
project="$root/tests/acceptance/codespaces-workstation/project"
cloudmake="$root/bin/cloudmake"

: "${CODESPACE:?set CODESPACE to an existing cloudmake anchor Codespace}"
: "${CLOUDMAKE_CODESPACES_IMAGE:?set CLOUDMAKE_CODESPACES_IMAGE to a digest-pinned public OCI image}"

temporary=$(mktemp -d "${TMPDIR:-/tmp}/cloudmake-codespaces.XXXXXX")
export CLOUDMAKE_CONFIG_HOME="$temporary/config"
export CLOUDMAKE_STATE_HOME="$temporary/state"
export CLOUDMAKE_CACHE_HOME="$temporary/cache"

cleanup() {
	"$cloudmake" -C "$project" --native verify >/dev/null 2>&1 || :
	"$cloudmake" -C "$project" --stop >/dev/null 2>&1 || :
	rm -rf "$temporary"
}
trap cleanup EXIT HUP INT TERM

selection=$(
	CODESPACE="$CODESPACE" "$cloudmake" -C "$project" \
		--use codespaces --image "$CLOUDMAKE_CODESPACES_IMAGE"
)
printf '%s\n' "$selection"
printf '%s\n' "$selection" | grep 'subsequent targets reuse this selection' >/dev/null

first=$("$cloudmake" -C "$project" verify)
printf '%s\n' "$first"
printf '%s\n' "$first" | grep 'oci-environment=provider-native' >/dev/null

one=$("$cloudmake" -C "$project" increment)
two=$("$cloudmake" -C "$project" increment)
printf '%s\n%s\n' "$one" "$two"
one_count=$(printf '%s\n' "$one" | sed -n 's/.*incremental workstation count=\([0-9][0-9]*\).*/\1/p')
two_count=$(printf '%s\n' "$two" | sed -n 's/.*incremental workstation count=\([0-9][0-9]*\).*/\1/p')
test -n "$one_count"
test -n "$two_count"
test "$two_count" -eq "$((one_count + 1))"

"$cloudmake" -C "$project" --stop
woken=$("$cloudmake" -C "$project" verify)
printf '%s\n' "$woken"
printf '%s\n' "$woken" | grep 'resource=started' >/dev/null
printf '%s\n' "$woken" | grep 'state=reused' >/dev/null

"$cloudmake" -C "$project" --collect dist export-artifact
test -f "$project/artifacts/result.txt"

"$cloudmake" -C "$project" --native verify
"$cloudmake" -C "$project" --stop
trap - EXIT HUP INT TERM
rm -rf "$temporary"

printf 'Codespaces provider-native OCI acceptance passed.\n'

#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
	echo "usage: $0 DESTINATION" >&2
	exit 2
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination=$1

clone_revision() {
	url=$1
	revision=$2
	checkout=$3
	git clone --quiet --depth 1 --filter=blob:none --no-checkout "$url" "$checkout"
	git -C "$checkout" fetch --quiet --depth 1 origin "$revision"
	git -C "$checkout" checkout --quiet --detach "$revision"
}

pin_image() {
	file=$1
	tagged=$2
	pinned=$3
	temporary=$file.cloudmake-tmp
	if ! grep -F "$tagged" "$file" >/dev/null; then
		echo "expected image reference is absent from $file: $tagged" >&2
		exit 1
	fi
	sed "s|$tagged|$pinned|" "$file" >"$temporary"
	mv "$temporary" "$file"
}

mkdir -p "$destination"
if find "$destination" -mindepth 1 -maxdepth 1 -print -quit | grep . >/dev/null; then
	echo "destination is not empty: $destination" >&2
	exit 1
fi

clone_revision https://github.com/microsoft/vscode-remote-try-cpp.git \
	22af031095a03864b8c2032b6498ff6d21e46c36 "$destination/cpp"
clone_revision https://github.com/microsoft/vscode-remote-try-go.git \
	f4575309350c5ca2f1495c28a13b4b07088e8cea "$destination/go"
clone_revision https://github.com/microsoft/vscode-remote-try-java.git \
	4638a925031f05cca946b8ce6ab640c433c93585 "$destination/java"
clone_revision https://github.com/microsoft/vscode-remote-try-node.git \
	42a8bcfd51e64ce623cb60260408c4b2d1f1a509 "$destination/node"
clone_revision https://github.com/microsoft/vscode-remote-try-python.git \
	e351212b72f76fb557c6f31956eb44756300b8b4 "$destination/python"
clone_revision https://github.com/microsoft/vscode-remote-try-rust.git \
	d3cb2a9843af67d20491c9fde829b2c77230847b "$destination/rust"
clone_revision https://github.com/devcontainers/templates.git \
	0d90e81192547f6464cf2ed84f56bcf2e558f526 "$destination/templates"

pin_image "$destination/go/.devcontainer/devcontainer.json" \
	mcr.microsoft.com/devcontainers/go:1-1.22-bookworm \
	mcr.microsoft.com/devcontainers/go@sha256:9d5f23d9cb2f27e71144d793368b231471a21b78e1a2cdbb593715d021bc020b
pin_image "$destination/java/.devcontainer/devcontainer.json" \
	mcr.microsoft.com/devcontainers/java:1-21 \
	mcr.microsoft.com/devcontainers/java@sha256:0af991049cded4b8d5a90d2614289ceec390779ad6a3e4b70957e2b4f3bb1230
pin_image "$destination/node/.devcontainer/devcontainer.json" \
	mcr.microsoft.com/devcontainers/javascript-node:1-18-bullseye \
	mcr.microsoft.com/devcontainers/javascript-node@sha256:4d188a9f3ccb5b36c8d0d060c56802eb4025de665885ba6dddd2843a4f6597f8
pin_image "$destination/python/.devcontainer/devcontainer.json" \
	mcr.microsoft.com/devcontainers/python:1-3.12 \
	mcr.microsoft.com/devcontainers/python@sha256:7876580dc67fd460fd962f004cbeb480027e9bbc0657096f1087db11f9eaff39
pin_image "$destination/rust/.devcontainer/devcontainer.json" \
	mcr.microsoft.com/devcontainers/rust:1-1-bullseye \
	mcr.microsoft.com/devcontainers/rust@sha256:6817e2f836956c5034933e52f305b6c1112b628d3fbad0e87f472a2839ad5fe0
pin_image "$destination/templates/src/ubuntu/.devcontainer/devcontainer.json" \
	'mcr.microsoft.com/devcontainers/base:${templateOption:imageVariant}' \
	mcr.microsoft.com/devcontainers/base@sha256:00e84e24112159d45c0262f07cb013cb58cb6a415f3e1c743d4a3115ac5d76c6

install -m 0644 "$script_dir/overlays/rust/Makefile" "$destination/rust/Makefile"
install -m 0644 "$script_dir/overlays/ubuntu/Makefile" \
	"$destination/templates/src/ubuntu/Makefile"

printf '%s\n' \
	"$destination/cpp" \
	"$destination/go" \
	"$destination/java" \
	"$destination/node" \
	"$destination/python" \
	"$destination/rust" \
	"$destination/templates/src/ubuntu"

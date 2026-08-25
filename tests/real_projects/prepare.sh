#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
	echo "usage: $0 DESTINATION" >&2
	exit 2
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination=$1

nvidia_url=https://github.com/NVIDIA/accelerated-computing-hub.git
nvidia_revision=a776efdfc2fba159a0aecced3e7c0dfafaf81b8b
nvidia_path=tutorials/cuda-cpp/notebooks/01.02-Execution-Spaces

gpu_mode_url=https://github.com/gpu-mode/lectures.git
gpu_mode_revision=b4df16e2b9512721c581fbcf4ea39b3d730cc0c4
gpu_mode_path=lecture_002/vector_addition

clone_sparse_revision() {
	url=$1
	revision=$2
	sparse_path=$3
	checkout=$4

	git clone --quiet --depth 1 --filter=blob:none --sparse --no-checkout "$url" "$checkout"
	git -C "$checkout" fetch --quiet --depth 1 origin "$revision"
	git -C "$checkout" sparse-checkout set "$sparse_path"
	git -C "$checkout" checkout --quiet --detach "$revision"
}

mkdir -p "$destination"

nvidia_checkout=$destination/accelerated-computing-hub
gpu_mode_checkout=$destination/gpu-mode-lectures

if [ -e "$nvidia_checkout" ] || [ -e "$gpu_mode_checkout" ]; then
	echo "destination already contains a real-project checkout: $destination" >&2
	exit 1
fi

clone_sparse_revision "$nvidia_url" "$nvidia_revision" "$nvidia_path" "$nvidia_checkout"
clone_sparse_revision "$gpu_mode_url" "$gpu_mode_revision" "$gpu_mode_path" "$gpu_mode_checkout"

install -m 0644 \
	"$script_dir/overlays/nvidia-cuda-cpp/Makefile" \
	"$nvidia_checkout/$nvidia_path/Makefile"
install -m 0644 \
	"$script_dir/overlays/gpu-mode-vector-addition/Makefile" \
	"$gpu_mode_checkout/$gpu_mode_path/Makefile"

printf '%s\n' \
	"$nvidia_checkout/$nvidia_path" \
	"$gpu_mode_checkout/$gpu_mode_path"

"""Prepare and preflight Cloudmake's provider-qualified Colab crun adapter."""

from __future__ import annotations

import base64
import glob
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


CONTROL = Path("/content/cloudmake-oci-control")
RUNNER = Path("/content/cloudmake-oci-runner.py")
RESULT = Path("/content/.cloud-build/oci-preflight.json")
PACKAGES = ("skopeo", "umoci", "crun")
NVIDIA_LIBRARY_DIR = Path("/usr/lib64-nvidia")
NVIDIA_SMI = Path("/opt/bin/.nvidia/nvidia-smi")


def decode(value: str) -> str:
    return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True).decode()


def atomic_failure(message: str) -> None:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{RESULT.name}.", suffix=".tmp", dir=RESULT.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "schema": 1,
                    "mode": "preflight",
                    "status": "infrastructure-failed",
                    "error": message,
                },
                stream,
                sort_keys=True,
            )
            stream.write("\n")
        os.replace(temporary, RESULT)
    finally:
        temporary.unlink(missing_ok=True)


def colab_nvidia_device_paths() -> list[str]:
    return [
        value
        for value in sorted(
            set(glob.glob("/dev/nvidia*")) | set(glob.glob("/dev/nvidia-caps/*"))
        )
        if stat.S_ISCHR(Path(value).stat().st_mode)
    ]


def generate_colab_nvidia_cdi(directory: Path, devices: list[str]) -> None:
    path = directory / "cloudmake-colab-nvidia.json"
    if "nvidia.com/gpu=all" not in devices:
        path.unlink(missing_ok=True)
        return
    libraries = NVIDIA_LIBRARY_DIR
    nvidia_smi = NVIDIA_SMI
    if not libraries.is_dir() or not nvidia_smi.is_file():
        raise RuntimeError(
            "Colab NVIDIA driver mounts are unavailable for CDI generation"
        )
    device_paths = colab_nvidia_device_paths()
    required = {"/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm"}
    if not required.issubset(device_paths):
        raise RuntimeError("Colab NVIDIA device nodes are incomplete")
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "cdiVersion": "0.6.0",
        "kind": "nvidia.com/gpu",
        "devices": [
            {
                "name": "all",
                "containerEdits": {
                    "env": [
                        "LD_LIBRARY_PATH=/usr/lib64-nvidia:/usr/local/cuda/lib64"
                    ],
                    "deviceNodes": [
                        {"path": value, "hostPath": value} for value in device_paths
                    ],
                    "mounts": [
                        {
                            "hostPath": os.fspath(libraries),
                            "containerPath": "/usr/lib64-nvidia",
                            "options": ["rbind", "ro"],
                        },
                        {
                            "hostPath": os.fspath(nvidia_smi),
                            "containerPath": "/usr/bin/nvidia-smi",
                            "options": ["bind", "ro"],
                        },
                    ],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    RESULT.unlink(missing_ok=True)
    try:
        lines = CONTROL.read_text(encoding="utf-8").splitlines()
        if len(lines) not in (5, 6):
            raise RuntimeError("invalid Colab OCI preparation control file")
        image = decode(lines[0])
        devices = json.loads(decode(lines[1]))
        source, cache, makefile = lines[2:5]
        runtimes = json.loads(decode(lines[5])) if len(lines) == 6 else ["crun"]
        if not isinstance(devices, list) or not all(
            isinstance(device, str) for device in devices
        ):
            raise RuntimeError("invalid Colab OCI CDI device list")
        if runtimes != ["crun"]:
            raise RuntimeError("Colab OCI execution requires its qualified crun profile")
        install_missing = [name for name in PACKAGES if shutil.which(name) is None]
        if install_missing:
            print(
                "[cloudmake] preparing Colab OCI runtime: "
                + ", ".join(install_missing),
                flush=True,
            )
            subprocess.run(["apt-get", "update", "-qq"], check=True)
            subprocess.run(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "-qq",
                    "--no-install-recommends",
                    *PACKAGES,
                ],
                check=True,
            )
        cdi_directory = Path(cache) / "cdi"
        generate_colab_nvidia_cdi(cdi_directory, devices)
        command = [
            sys.executable,
            os.fspath(RUNNER),
            "--mode",
            "preflight",
            "--image",
            image,
            "--runtime",
            "auto",
            "--source",
            source,
            "--cache",
            cache,
            "--makefile",
            makefile,
            "--rootless-workspace-owner",
            "65534:65534",
            "--cdi-spec-dir",
            os.fspath(cdi_directory),
            "--result",
            os.fspath(RESULT),
        ]
        for device in devices:
            command.extend(["--device", device])
        for runtime in runtimes:
            command.extend(["--runtime-candidate", runtime])
        completed = subprocess.run(command, check=False)
        if completed.returncode and not RESULT.is_file():
            atomic_failure(
                f"OCI preflight exited with status {completed.returncode} without a receipt"
            )
    except Exception as error:
        atomic_failure(str(error) or type(error).__name__)
        print(f"[cloudmake] OCI infrastructure failure: {error}", file=sys.stderr)


if __name__ == "__main__":
    # `colab exec -f` runs in IPython; return normally to avoid a synthetic
    # SystemExit traceback. The host validates RESULT independently.
    main()

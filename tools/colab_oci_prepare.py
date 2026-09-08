"""Prepare and preflight the restricted Colab OCI runner."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CONTROL = Path("/content/cloudmake-oci-control")
RUNNER = Path("/content/cloudmake-oci-runner.py")
RESULT = Path("/content/.cloud-build/oci-preflight.json")
REQUIRED = ("skopeo", "umoci", "mount", "umount")
PACKAGES = ("skopeo", "umoci")


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


def main() -> None:
    RESULT.unlink(missing_ok=True)
    try:
        lines = CONTROL.read_text(encoding="utf-8").splitlines()
        if len(lines) not in (5, 6):
            raise RuntimeError("invalid Colab OCI preparation control file")
        image = decode(lines[0])
        devices = json.loads(decode(lines[1]))
        source, cache, makefile = lines[2:5]
        runtimes = json.loads(decode(lines[5])) if len(lines) == 6 else ["chroot"]
        if devices:
            raise RuntimeError("Colab's restricted chroot OCI profile cannot apply CDI devices")
        base_missing = [
            name for name in REQUIRED if name not in PACKAGES and shutil.which(name) is None
        ]
        if base_missing:
            raise RuntimeError(
                "Colab base VM is missing restricted OCI command(s): "
                + ", ".join(base_missing)
            )
        install_missing = [name for name in PACKAGES if shutil.which(name) is None]
        if install_missing:
            print(
                "[cloudmake] preparing restricted OCI runtime: "
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
        command = [
            sys.executable,
            os.fspath(RUNNER),
            "--mode",
            "preflight",
            "--image",
            image,
            "--runtime",
            "chroot",
            "--source",
            source,
            "--cache",
            cache,
            "--makefile",
            makefile,
            "--rootless-workspace-owner",
            "65534:65534",
            "--result",
            os.fspath(RESULT),
        ]
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

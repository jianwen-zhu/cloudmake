from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile


def boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean value, got {value!r}")


parser = argparse.ArgumentParser(description="Prepare a self-contained Kaggle notebook run")
parser.add_argument("--template", type=Path, required=True)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--owner", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--metadata", type=Path, required=True)
parser.add_argument("--kernel-ref", required=True)
parser.add_argument("--title", required=True)
parser.add_argument("--target", default="")
parser.add_argument("--target-b64", default="")
parser.add_argument("--jobs", type=int, required=True)
parser.add_argument("--makefile", default="Makefile.build")
parser.add_argument("--arguments-b64", default="W10=")
parser.add_argument("--collect-dir-b64", default="")
parser.add_argument("--private", type=boolean, required=True)
parser.add_argument("--enable-internet", type=boolean, required=True)
parser.add_argument("--accelerator", default="")
parser.add_argument("--checkpoint", action="store_true")
parser.add_argument("--workspace-id", default="")
parser.add_argument("--checkpoint-head", type=Path)
parser.add_argument("--source-manifest", type=Path)
parser.add_argument("--dispatch", type=Path)
parser.add_argument(
    "--remote-helper", type=Path, default=Path(__file__).with_name("kaggle_remote.py")
)
parser.add_argument(
    "--oci-helper", type=Path, default=Path(__file__).with_name("oci_runner.py")
)
parser.add_argument("--runner", choices=("native", "oci"), default="native")
parser.add_argument("--image-b64", default="")
parser.add_argument("--devices-b64", default="W10=")
parser.add_argument("--runtimes-b64", default="W10=")
arguments = parser.parse_args()
if arguments.dispatch is None:
    arguments.dispatch = arguments.output.with_name("dispatch.json")

if bool(arguments.target) == bool(arguments.target_b64):
    parser.error("exactly one of --target and --target-b64 is required")
if arguments.target_b64:
    try:
        target = base64.b64decode(
            arguments.target_b64.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except Exception as error:
        parser.error(f"invalid --target-b64: {error}")
else:
    target = arguments.target

collect_dir = None
if arguments.collect_dir_b64:
    try:
        collect_dir = base64.b64decode(
            arguments.collect_dir_b64.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except Exception as error:
        parser.error(f"invalid --collect-dir-b64: {error}")
    collect_path = PurePosixPath(collect_dir)
    if not collect_dir or collect_path.is_absolute() or ".." in collect_path.parts:
        parser.error("collection directory must be a safe project-relative path")

makefile = PurePosixPath(arguments.makefile)
if (
    not target
    or "\n" in target
    or not arguments.makefile
    or makefile.is_absolute()
    or ".." in makefile.parts
):
    parser.error("target and makefile must be non-empty safe relative values")
try:
    decoded_arguments = json.loads(
        base64.urlsafe_b64decode(arguments.arguments_b64.encode("ascii")).decode("utf-8")
    )
except Exception as error:
    parser.error(f"invalid --arguments-b64: {error}")
if not isinstance(decoded_arguments, list) or not all(
    isinstance(value, str) for value in decoded_arguments
):
    parser.error("--arguments-b64 must encode a JSON string list")

if arguments.checkpoint:
    if re.fullmatch(r"[0-9a-f]{24}", arguments.workspace_id) is None:
        parser.error("checkpoint mode requires a valid workspace ID")
    if arguments.checkpoint_head is None or arguments.source_manifest is None:
        parser.error("checkpoint mode requires head and source-manifest paths")
    if not arguments.private:
        parser.error("checkpoint mode requires a private Kaggle kernel")


def decoded_json_list(value: str, description: str) -> list[str]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode())
    except Exception as error:
        parser.error(f"invalid encoded {description}: {error}")
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        parser.error(f"encoded {description} must be a JSON string list")
    return decoded


devices = decoded_json_list(arguments.devices_b64, "OCI devices")
runtimes = decoded_json_list(arguments.runtimes_b64, "OCI runtimes")
image = ""
if arguments.runner == "oci":
    if not arguments.image_b64 or not runtimes:
        parser.error("OCI mode requires an image and backend runtime candidates")
    try:
        image = base64.urlsafe_b64decode(arguments.image_b64.encode("ascii")).decode()
    except Exception as error:
        parser.error(f"invalid encoded OCI image: {error}")


def load_head() -> dict:
    if not arguments.checkpoint or arguments.checkpoint_head is None:
        return {}
    try:
        value = json.loads(arguments.checkpoint_head.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as error:
        parser.error(f"invalid Kaggle checkpoint head: {error}")
    if (
        not isinstance(value, dict)
        or value.get("schema") != 1
        or value.get("workspace_id") != arguments.workspace_id
        or value.get("slot") not in {"a", "b"}
        or not isinstance(value.get("kernel_ref"), str)
    ):
        parser.error("invalid Kaggle checkpoint head")
    return value


base_owner, separator, base_slug = arguments.kernel_ref.partition("/")
if not separator or not base_owner or not base_slug:
    parser.error("kernel reference must be OWNER/SLUG")
head = load_head()
if arguments.checkpoint:
    slot = "b" if head.get("slot") == "a" else "a"
    active_ref = f"{base_owner}/cloudmake-ws-{arguments.workspace_id}-{slot}"
    previous_ref = head.get("kernel_ref", "")
else:
    slot = ""
    active_ref = arguments.kernel_ref
    previous_ref = ""

source_manifest = {}
if arguments.source_manifest is not None:
    try:
        source_manifest = json.loads(arguments.source_manifest.read_text(encoding="utf-8"))
    except Exception as error:
        parser.error(f"invalid source manifest: {error}")

notebook = json.loads(arguments.template.read_text(encoding="utf-8"))
owner = json.loads(arguments.owner.read_text(encoding="utf-8"))
control = {
    "schema": 1,
    "project_id": owner["project_id"],
    "workspace_id": arguments.workspace_id,
    "checkpoint": arguments.checkpoint,
    "previous_kernel_ref": previous_ref,
    "active_kernel_ref": active_ref,
    "source_manifest": source_manifest,
    "target": target,
    "jobs": arguments.jobs,
    "makefile": arguments.makefile,
    "project_arguments": decoded_arguments,
    "collect_dir": collect_dir,
    "runner": arguments.runner,
    "image": image,
    "devices": devices,
    "runtime_candidates": runtimes,
    # Explicit target egress is checked before Make. OCI preparation performs
    # narrower package/registry probes only when a cold cache actually needs
    # them, allowing a restored warm image to execute offline.
    "network_required": arguments.enable_internet,
}
notebook.setdefault("metadata", {})["cloudmake"] = {
    "schema": owner["schema"],
    "project_id": owner["project_id"],
    "project_name": owner["project_name"],
    "source_path": owner["source_path"],
    "hostname": owner["hostname"],
}
payload = base64.b64encode(arguments.archive.read_bytes()).decode("ascii")
replacements = {
    "__SOURCE_ARCHIVE_B64__": payload,
    "__REQUESTED_TARGET_B64__": base64.urlsafe_b64encode(
        target.encode("utf-8")
    ).decode("ascii"),
    "__JOBS__": str(arguments.jobs),
    "__MAKEFILE_B64__": base64.urlsafe_b64encode(
        arguments.makefile.encode("utf-8")
    ).decode("ascii"),
    "__PROJECT_ARGUMENTS_B64__": arguments.arguments_b64,
    "__COLLECT_DIR_B64__": arguments.collect_dir_b64,
    "__KAGGLE_CONTROL_B64__": base64.b64encode(
        json.dumps(control, separators=(",", ":")).encode("utf-8")
    ).decode("ascii"),
    "__KAGGLE_REMOTE_HELPER_B64__": base64.b64encode(
        arguments.remote_helper.read_bytes()
    ).decode("ascii"),
    "__OCI_RUNNER_HELPER_B64__": base64.b64encode(
        arguments.oci_helper.read_bytes()
    ).decode("ascii"),
}

for cell in notebook["cells"]:
    source = cell.get("source", [])
    source_lines = [source] if isinstance(source, str) else source
    for token, replacement in replacements.items():
        source_lines = [line.replace(token, replacement) for line in source_lines]
    cell["source"] = source_lines
    if cell.get("cell_type") == "code":
        cell["execution_count"] = None
        cell["outputs"] = []

arguments.output.write_text(json.dumps(notebook, indent=2) + "\n", encoding="utf-8")

accelerator = arguments.accelerator.strip()
metadata = {
    "id": active_ref,
    "title": (
        active_ref.split("/", 1)[1].replace("-", " ")
        if arguments.checkpoint else arguments.title
    ),
    "code_file": arguments.output.name,
    "language": "python",
    "kernel_type": "notebook",
    "is_private": arguments.private,
    "enable_gpu": accelerator.startswith("Nvidia"),
    "enable_tpu": accelerator.startswith("Tpu"),
    "enable_internet": arguments.enable_internet or arguments.runner == "oci",
    "machine_shape": accelerator,
    "dataset_sources": [],
    "competition_sources": [],
    "kernel_sources": [previous_ref] if previous_ref else [],
    "model_sources": [],
}
arguments.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

dispatch = {
    "schema": 1,
    "checkpoint": arguments.checkpoint,
    "workspace_id": arguments.workspace_id,
    "slot": slot,
    "kernel_ref": active_ref,
    "previous_kernel_ref": previous_ref,
}
arguments.dispatch.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary_name = tempfile.mkstemp(
    prefix=f".{arguments.dispatch.name}.", suffix=".tmp", dir=arguments.dispatch.parent
)
temporary = Path(temporary_name)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(dispatch, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, arguments.dispatch)
finally:
    temporary.unlink(missing_ok=True)

print(f"Prepared private notebook target {target!r} for {active_ref}")

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path, PurePosixPath


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
arguments = parser.parse_args()

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

notebook = json.loads(arguments.template.read_text(encoding="utf-8"))
owner = json.loads(arguments.owner.read_text(encoding="utf-8"))
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
    "id": arguments.kernel_ref,
    "title": arguments.title,
    "code_file": arguments.output.name,
    "language": "python",
    "kernel_type": "notebook",
    "is_private": arguments.private,
    "enable_gpu": accelerator.startswith("Nvidia"),
    "enable_tpu": accelerator.startswith("Tpu"),
    "enable_internet": arguments.enable_internet,
    "machine_shape": accelerator,
    "dataset_sources": [],
    "competition_sources": [],
    "kernel_sources": [],
    "model_sources": [],
}
arguments.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

print(f"Prepared private notebook target {target!r} for {arguments.kernel_ref}")

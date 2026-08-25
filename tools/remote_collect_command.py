from __future__ import annotations

import argparse
import base64
import shlex
from pathlib import PurePosixPath


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Construct a quoted remote artifact collection command"
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--directory-b64", required=True)
    parser.add_argument("--archive", required=True)
    arguments = parser.parse_args()

    try:
        directory = base64.b64decode(
            arguments.directory_b64.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except Exception as error:
        parser.error(f"invalid --directory-b64: {error}")

    relative = PurePosixPath(directory)
    if not directory or relative.is_absolute() or ".." in relative.parts:
        parser.error("collection directory must be a safe project-relative path")

    source = PurePosixPath(arguments.source)
    archive = PurePosixPath(arguments.archive)
    collection = source.joinpath(relative)
    temporary = PurePosixPath(f"{archive}.tmp")
    quoted_collection = shlex.quote(str(collection))
    quoted_archive = shlex.quote(str(archive))
    quoted_temporary = shlex.quote(str(temporary))
    message = shlex.quote(f"collection directory does not exist: {directory}")
    print(
        f"if test ! -d {quoted_collection}; then echo {message} >&2; exit 2; fi; "
        f"tar -C {quoted_collection} -czf {quoted_temporary} . && "
        f"mv {quoted_temporary} {quoted_archive}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

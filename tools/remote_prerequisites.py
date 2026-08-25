from __future__ import annotations

import shutil
import sys


REQUIRED_COMMANDS = ("make", "tar")
missing = [command for command in REQUIRED_COMMANDS if shutil.which(command) is None]
if missing:
    print(
        "Missing required remote command(s): " + ", ".join(missing),
        file=sys.stderr,
    )
    raise SystemExit(2)
print("[cloudmake] Remote prerequisites are ready.")

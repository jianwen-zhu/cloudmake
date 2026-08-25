#!/usr/bin/env python3
"""Validate the exported OpenSSH alias without interpolating it into a shell."""

from __future__ import annotations

import os
import re
import sys


host = os.environ.get("SSH_HOST", "")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", host):
    print(
        "SSH_HOST must be a simple OpenSSH Host alias beginning with a letter or "
        "number and containing only letters, numbers, dot, dash, and underscore",
        file=sys.stderr,
    )
    raise SystemExit(2)

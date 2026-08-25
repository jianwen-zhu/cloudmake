#!/usr/bin/env python3
"""Validate the exported OpenSSH alias without interpolating it into a shell."""

from __future__ import annotations

import os
import re
import sys


host = os.environ.get("LAB_HOST", "")
if not re.fullmatch(r"[A-Za-z0-9._-]+", host):
    print(
        "LAB_HOST must be a simple OpenSSH Host alias containing only letters, "
        "numbers, dot, dash, and underscore",
        file=sys.stderr,
    )
    raise SystemExit(2)

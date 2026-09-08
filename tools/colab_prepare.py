from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path("/content/.cloud-build/workspace")
INCOMING = Path("/content/cloud-build-prepared")
PREPARED = ROOT / ".cloudmake-prepared"

ROOT.mkdir(parents=True, exist_ok=True)
temporary = PREPARED.with_suffix(".new")
shutil.copyfile(INCOMING, temporary)
temporary.replace(PREPARED)
print("Recorded session preparation receipt")

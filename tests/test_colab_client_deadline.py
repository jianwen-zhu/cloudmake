import subprocess
import sys

from conftest import PROJECT_ROOT


def test_colab_client_deadline_also_kills_children_holding_output_open(tmp_path):
    command = [
        sys.executable,
        str(PROJECT_ROOT / "backend/colab-notebook/client_deadline.py"),
        "--timeout",
        "1",
        "--",
        sys.executable,
        "-c",
        (
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "print('child started', flush=True); time.sleep(60)"
        ),
    ]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert result.returncode == 124
    assert "child started" in result.stdout
    assert "exceeded its 1s deadline" in result.stderr

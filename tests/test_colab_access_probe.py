from __future__ import annotations

import runpy
import subprocess

from conftest import PROJECT_ROOT


def test_colab_access_probe_bounds_the_command_and_closes_stdin(monkeypatch):
    module = runpy.run_path(str(PROJECT_ROOT / "backend" / "colab-notebook" / "access_probe.py"))

    def timed_out(command, *, stdin, timeout, **kwargs):
        assert command == ["test-colab-client", "sessions"]
        assert stdin == subprocess.DEVNULL
        assert timeout == 10
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(subprocess, "run", timed_out)
    assert module["probe"]("test-colab-client") == "transient"

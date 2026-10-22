"""Los entrypoints cargan dotenv antes de importar configuración del dominio."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINTS = (
    "airi.__main__",
    "airi.observability.cli",
    "airi.observability.replay",
)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_entrypoint_loads_dotenv_before_domain_constants(entrypoint):
    code = r"""
import dotenv
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory

original_load_dotenv = dotenv.load_dotenv
with TemporaryDirectory() as temp_dir:
    env_file = Path(temp_dir, ".env")
    env_file.write_text("DATE_MAX_SECONDS=600\n")
    dotenv.load_dotenv = lambda *args, **kwargs: original_load_dotenv(
        dotenv_path=env_file, override=True
    )
    importlib.import_module(os.environ["ENTRYPOINT_MODULE"])
    from airi.domain.constants import DATE_MAX_SECONDS
    assert DATE_MAX_SECONDS == 600
"""
    env = os.environ.copy()
    env.pop("DATE_MAX_SECONDS", None)
    env["ENTRYPOINT_MODULE"] = entrypoint
    source_path = str(ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (source_path, env.get("PYTHONPATH")))
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

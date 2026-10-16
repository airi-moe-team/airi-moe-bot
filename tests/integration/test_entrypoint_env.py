"""Regresión: el entry point carga `.env` antes de fijar las constantes.

Las constantes de `airi.domain.constants` se leen del entorno en el momento
del import. Si `load_dotenv()` se ejecutara después de importarlas (el bug
original), el `.env` se ignoraría. Este test arranca un proceso hijo con un
`.env` propio y comprueba que `airi.__main__` respeta el orden de carga.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# Importa el entry point (que ejecuta `load_dotenv()`) y luego la constante.
_PROBE = (
    "import airi.__main__;"
    "from airi.domain.constants import DATE_MAX_SECONDS;"
    "print(DATE_MAX_SECONDS)"
)


def test_entrypoint_loads_dotenv_before_constants(tmp_path):
    (tmp_path / ".env").write_text("DATE_MAX_SECONDS=600\n", encoding="utf-8")

    env = dict(os.environ)
    env.pop("DATE_MAX_SECONDS", None)  # el valor debe venir del .env temporal
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "600"

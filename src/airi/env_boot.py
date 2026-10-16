"""Carga el `.env` como efecto lateral al importar el módulo.

Existe porque varias constantes del dominio (`airi.domain.constants`) leen el
entorno **en el momento del import**. Cualquier entry point (`airi`,
`airi-trace`, `airi-replay`) debe importar este módulo **antes** que cualquier
otro submódulo de `airi` que fije esos valores, o el `.env` se ignorará.

Los tests quedan a salvo: `tests/conftest.py` neutraliza `dotenv.load_dotenv`.
"""

from dotenv import load_dotenv

load_dotenv()

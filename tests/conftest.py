import os
import sys

import dotenv

# Asegura que el root del proyecto esté en sys.path para poder importar bot/game.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tests herméticos: neutralizamos load_dotenv() para que el .env personal del
# desarrollador no cambie los valores por defecto del código durante la suite.
# Debe ejecutarse antes de que los módulos de test importen bot/game.
dotenv.load_dotenv = lambda *args, **kwargs: False

# bot.py exige estas dos variables al importarse; damos valores ficticios para
# que la suite no dependa del .env real.
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("CHANNEL_ID", "1")
# Las pruebas históricas no deben consumir una respuesta adicional del FakeLLM;
# los tests específicos de conversation_review habilitan explícitamente el flag.
os.environ.setdefault("AIRI_CONVERSATION_REVIEW", "false")

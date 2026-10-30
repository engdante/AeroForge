"""
_env.py — обща подготовка за тестовете.

Прави две неща при първото си импортиране:
  1. добавя `app/` в sys.path, за да се внася пакетът `core`;
  2. ИЗОЛИРА потребителските настройки — тестовете никога не четат и не
     пишат реалния settings.json на потребителя.
"""

import os
import sys
import tempfile

APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core import settings  # noqa: E402

# временен файл за настройки (не съществува → вградени стойности)
settings.SETTINGS_PATH = os.path.join(tempfile.gettempdir(),
                                      "aeroforge_tests_settings.json")
try:
    if os.path.exists(settings.SETTINGS_PATH):
        os.remove(settings.SETTINGS_PATH)
except OSError:
    pass
settings.load()

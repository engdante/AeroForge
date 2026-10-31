# Ръководство за разработка

Този документ е кратка карта за промени в кода. Инструкциите за инсталация и
употреба остават в [`README.md`](../README.md); правилата за coding агенти са в
[`AGENTS.md`](../AGENTS.md).

## Бърз старт

От корена на проекта:

```bash
# Windows
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

# Linux / macOS
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

Тестовете са с вградения `unittest`. Настройките се изолират от реалния
`settings.json` чрез `tests/_env.py`. `tests/test_viewer3d.py` използва Node за
JavaScript/WebGL smoke тестове и ги пропуска, ако Node не е инсталиран.

За бърз цикъл пускай конкретен файл или клас:

```bash
python -m unittest discover -s tests -p "test_design.py"
python -m unittest discover -s tests -p "test_viewer3d.py"
```

При промени в браузърния код провери синтаксиса:

```bash
node --check app/web/js/api.js
```

Приложението се стартира с `start.bat` (Windows) или `./start.sh` (Linux/macOS).
Скриптовете създават `.venv` и инсталират `app/requirements.txt`. Зависимост за
изпълнение е Eel; Node се използва само за допълнителни JavaScript тестове.

## Архитектурна карта

```text
app/web/index.html + app/web/js/*
        │ Eel bridge (app/web/js/api.js)
        ▼
app/server.py — изложени Eel функции, файлове и UI интеграция
        ▼
app/core/design.py — нормализация на входа, изчислителен поток и резултат
        ├─ aero / propulsion / structure / cg / weight / printcost
        ├─ checks.py — инженерни проверки и обяснения за резултата
        ├─ fuselage / layout / geometry3d
        └─ assembly / printgeom / export_* / model_export / export_job
```

Ориентири по тип задача:

| Задача | Начална точка | Тестове |
|---|---|---|
| Аеродинамика, задвижване, якост | `app/core/aero.py`, `propulsion.py`, `structure.py` | `test_aero.py`, `test_propulsion.py`, `test_structure.py` |
| Входове, изчисление и резултат | `app/core/design.py` | `test_design.py`, `test_config.py` |
| Проверки и обяснения | `app/core/checks.py` (`design.build_checks` остава съвместим) | `test_checks.py`, `test_design.py` |
| Eel API и файлово съхранение | `app/server.py` | `test_server.py` |
| 3D преглед за браузъра | `app/web/js/viewer3d.js` | `test_viewer3d.py` |
| CAD и сглобяване | `app/core/assembly.py`, `app/core/solidcraft_export.py` | `test_assembly.py`, `test_solidcraft.py`, `test_solids.py` |
| Печатна геометрия и mesh/STL | `app/core/printgeom.py`, `stl.py`, `meshcheck.py` | `test_printgeom.py`, `test_stl.py`, `test_solids.py` |
| Експортна задача и файлови формати | `app/core/export_job.py`, `export_*.py`, `model_export.py` | `test_export_job.py`, `test_export_formats.py` |
| Потребителски настройки | `app/core/settings.py` | `test_settings.py`, `test_server.py` |

## Договорености, които лесно се нарушават

- Core модулите са обикновени Python функции и не трябва да зависят от Eel/UI.
  Eel мостът е в `app/server.py`.
- Входните данни от UI минават през нормализацията в `design.py`. Запазвай
  съвместимостта със стари/непълни входове и валидирай невалидни числови стойности.
- Проверявай имената на полетата в резултатния dict и Eel API преди промяна:
  браузърът и отчетите ги използват.
- Следвай единиците и координатната система, описани в потребителския README и
  CAD export README-ите. Геометричните промени трябва да пазят затвореност,
  положителен обем и симетрия там, където се очаква.
- Настройките за тестове трябва да останат изолирани; не насочвай тестовете към
  реалния `settings.json`.
- `AeroForge.spec` поддържа списък `hiddenimports` за PyInstaller. При добавяне
  на core модул провери дали е откриваем при пакетиране и актуализирай spec-а,
  ако автоматичното откриване не е достатъчно.

## Структура и тестове

- `app/core/` — изчисления, геометрия и експорти.
- `app/web/` — статичен HTML/CSS и vanilla JavaScript; няма npm build стъпка.
- `tests/` — регресионни и интеграционни тестове; споделен setup е `_env.py`.
- `designs/`, `exports/`, `settings.json` — локални/потребителски данни, не са
  изходен код и не се включват в Git.

При промяна на формат или структура на експорт актуализирай тестовете и
съответните описания в `README.md`; генерираните изходни файлове сами по себе си
не са източник на истина.

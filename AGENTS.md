# Instrucciones para agentes de código

Victoria II Mod Studio: editor de mods de Victoria II en Python (PySide6, numpy, Pillow), con pruebas `unittest`.
El estado del proyecto está en `CONTINUAR_EN_CLAUDE_CODE.md`; el diseño, en `docs/diseno/wizard.md`; el código
existente, en `ARCHITECTURE.md`.

**Si vienes a hacer la iteración 4 (núcleo):** tu encargo está en `docs/handoff/opencode/ENCARGO.md`. Léelo
entero, y con él `REGLAS.md` y `PRUEBAS.md` de la misma carpeta, antes de escribir código. Trabaja en la rama
`opencode/it4-nucleo` y rellena `docs/handoff/opencode/INFORME.md` al acabar cada fase.

**Si te piden el corte vertical del motor de esquemas:** tu encargo es `docs/handoff/opencode/ENCARGO_MOTOR.md`
(no `ENCARGO.md`), en la rama `opencode/it4-motor`, con su informe en `INFORME_MOTOR.md`.

Lo imprescindible, para cualquier tarea:

- Responde al usuario en **español**. Docstrings y comentarios en español; identificadores en inglés.
- `vic2studio.core` no importa Qt. Sintaxis de Python 3.10 en `src/`. Sin dependencias nuevas.
- El código no escribe archivos fuera de `core/fileio.py` y el diario (`tests/test_arch_writes.py`): se cambian
  documentos del `Workspace`, dentro de una transacción, y se guarda con el diario.
- Lo que no se edita se conserva byte a byte. Leer nunca escribe.
- Textos ES y EN a la par; ningún texto visible escrito en el código.
- **Nunca** subas datos de Paradox (archivos del juego o líneas copiadas de ellos). El corpus vive fuera del
  repositorio y solo se usan copias. Nunca abras el mod real del usuario como proyecto.
- Batería: `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests` (sin corpus: `OK (skipped=40)`).
- No abras PR, no fusiones, no toques `main` ni ramas ajenas, no reescribas historia ya subida.

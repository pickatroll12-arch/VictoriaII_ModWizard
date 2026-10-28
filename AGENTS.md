# Instrucciones para agentes de código

Victoria II Mod Studio: editor de mods de Victoria II en Python (PySide6, numpy, Pillow), con pruebas `unittest`.
El estado del proyecto está en `CONTINUAR_EN_CLAUDE_CODE.md`; el diseño, en `docs/diseno/wizard.md`; el código
existente, en `ARCHITECTURE.md`.

**Si vienes a terminar la iteración 4:** tu encargo está en `docs/handoff/opencode/ENCARGO_IT4.md`. Léelo
entero, y con él `REGLAS.md` y `PRUEBAS.md` de la misma carpeta, antes de escribir código. Trabaja en la rama
`opencode/it4-claude` y rellena `docs/handoff/opencode/INFORME_IT4.md` al acabar cada fase.

`ENCARGO.md` y `ENCARGO_MOTOR.md` son encargos anteriores, ya hechos o sustituidos: no los ejecutes. Sus informes
(`INFORME_MOTOR.md` e `INFORME_EDITOR.md`) sí son lectura obligada si tocas el motor o el editor.

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

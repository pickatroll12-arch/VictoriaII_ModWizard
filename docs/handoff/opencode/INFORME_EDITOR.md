# Informe: editor de texto en Proyecto › Archivos

Rama `opencode/editor-texto`, creada desde `claude/keen-fermi-nw8itc`.
Este informe cubre solo el encargo `Encargo editor texto deepseek.md`.

## Estado por fase

- **Fase 0.** Rama creada y entorno preparado (`.venv` 3.12 y `.venv310` 3.10). La batería de partida **no
  coincide con la cifra de `PRUEBAS.md`**: esta rama tiene 1498 pruebas y 29 omitidas, no 1494/31. Además fallan
  4 pruebas ajenas al editor (ver «Línea base»).
- **Fase 1.** `core/textsplice.py` y `tests/test_textsplice.py`: 15 pruebas en verde.
- **Fase 2.** `ui/viewers/script_editor.py` y `tests/test_ui_script_editor.py` (criterios 1-10): 11 pruebas en
  verde. Todavía sin tocar Archivos.
- **Fase 3.** Botón «Editar», señal `edit_requested`, integración en Archivos y `main_window.py`, textos ES/EN.
  16 pruebas propias en verde (criterios 1-12 y las de integración).
- **Fase 4.** Pendiente.

## Línea base (fase 0)

`QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests`:

```text
Ran 1498 tests in 247.631s
FAILED (failures=4, skipped=29)
```

Los fallos son de la rama antes de este encargo, no del editor:

| Prueba | Motivo observado |
|---|---|
| `test_tasks.GarbageCollectorTests.test_garbage_frozen_with_a_large_result_is_collected_once_it_is_released` | `gc.get_freeze_count()` queda en 375 con Python 3.12; con 3.10 pasa. |
| `test_ui_palette.BannerTests.test_it_folds_at_1100_px_and_shows_everything_at_1920` (es/en) | «saveButton recortado»; depende de las métricas de la fuente instalada. |
| `test_ui_smoke.MainWindowTests.test_rail_is_a_column_with_room_and_a_strip_when_narrow` | «Regiones» recortado en la franja; depende de las métricas de la fuente. |

El entorno no traía `fonts-dejavu` (el README lo pide); se instalaron DejaVu Serif/Sans/Mono en el perfil del
usuario. Aun así, la combinación de fuentes del sistema (P052/Noto Serif) no reproduce las métricas con las que
se escribieron esas dos pruebas de disposición. No se tocó código de la interfaz para maquillarlas.

## Archivos

### `src/vic2studio/core/textsplice.py` (nuevo)

`normalize_newlines` y `splice_text`. Corta por `\r\n`, `\r` y `\n` con una expresión regular (no
`str.splitlines`), compara las líneas con `difflib.SequenceMatcher(autojunk=False)` y copia de `original` los
tramos iguales con su salto exacto. Los tramos nuevos usan el salto pedido y la última línea solo lleva salto si
la vista nueva lo lleva.

### `tests/test_textsplice.py` (nuevo)

Identidad en vacío, sin salto final, CRLF, LF, CR suelto y saltos mezclados; cambio de una línea CRLF; añadir,
borrar e insertar; quitar y poner el salto final; mezcla de saltos; precondición.

### `src/vic2studio/ui/viewers/script_editor.py` (nuevo)

`ScriptEditor(QWidget)` con barra (nombre, capa, sintaxis, estado), `QPlainTextEdit` mono sin ajuste y sin
deshacer propio, temporizador de 500 ms, `_commit` con `Session.edit(merge_key=...)` + `replace_text`, aviso de
carácter no codificable, recarga por `documentsChanged` conservando cursor y scroll, y `eventFilter` que deja
pasar Ctrl+Z/Ctrl+Y a la ventana.

### `src/vic2studio/ui/pages/project_page.py`

`edit_requested = Signal(object)`, un `QToolButton` «Editar» en la cabecera del visor Clausewitz, visible solo
cuando se muestra un script, y `_request_edit`. Nada más de la página cambia.

### `src/vic2studio/ui/halls/project/files.py`

`ScriptSection` crea el `ScriptEditor`, lo añade a `preview_stack`, conecta `edit_requested`, abre directamente
en el editor lo que tiene cambios sin guardar y vuelve al visor con «Volver a la vista» (confirmando antes).
`FilesPage.open_file` desvía al editor los documentos que solo están en memoria.

### `src/vic2studio/ui/main_window.py`

`commit_edits` confirma también el editor; `undo` y `redo` llaman a `commit_edits` antes de deshacer o rehacer.

### `src/vic2studio/i18n/es.json` y `en.json`

Claves `editor.*` en ES y EN, en orden alfabético.

## Criterios

| # | Estado | Prueba |
|---|---|---|
| 1 | cumple | `test_ui_script_editor.OpenTests.test_criterion1_opening_without_typing_writes_nothing` |
| 2 | cumple | `test_ui_script_editor.SaveTests.test_criterion2_mod_file_changes_only_that_line_and_keeps_crlf_and_cp1252` |
| 3 | cumple | `test_ui_script_editor.SaveTests.test_criterion3_game_only_file_is_copied_to_the_mod_and_the_game_is_untouched` |
| 4 | cumple | `test_ui_script_editor.UndoTests.test_criterion4_typing_is_one_undo_step_and_redo_puts_it_back` |
| 5 | cumple | `test_ui_script_editor.UnencodableTests.test_criterion5_a_character_outside_cp1252_never_reaches_the_document` |
| 6 | cumple | `test_ui_script_editor.SaveTests.test_criterion6_an_unclosed_brace_is_reported_and_saving_still_works` |
| 7 | cumple | `test_ui_script_editor.ReadOnlyProjectTests.test_criterion7_a_read_only_project_cannot_be_edited_and_says_why` |
| 8 | cumple | `test_ui_script_editor.OpenTests.test_criterion8_commit_pending_applies_before_the_timer` |
| 9 | cumple | `test_ui_script_editor.ExternalChangeTests.test_criterion9_an_external_transaction_reloads_the_editor` |
| 10 | cumple | `test_ui_script_editor.NewlineTests.test_criterion10_mixed_newlines_keep_the_untouched_lines` |
| 11 | cumple | `test_ui_script_editor.WindowTests.test_criterion11_ctrl_z_with_the_editor_focused_uses_the_application_undo` |
| 12 | cumple | `test_ui_script_editor.CatalogTests.test_criterion12_the_editor_keys_exist_in_spanish_and_english` |

## Batería final

Pendiente de la fase 4 (3.12 y 3.10).

## Mutantes

Pendiente de la fase 4.

## Peticiones para Claude y dudas

- `PRUEBAS.md` y `REGLAS.md` hablan de 1494 pruebas y `skipped=31`; en esta rama hay 1498 y 29. Conviene
  actualizar la cifra de referencia.
- La línea base no está verde por las pruebas de disposición y `gc.freeze` descritas arriba, que no tocan el
  editor.

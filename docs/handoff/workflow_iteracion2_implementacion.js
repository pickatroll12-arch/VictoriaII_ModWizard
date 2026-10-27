export const meta = {
  name: 'iteracion-2-implementacion',
  description: 'Iteración 2 (cimientos): agente A implementa el núcleo y agente B el descriptor y la interfaz, cada uno en su worktree, contra el commit de contrato',
  phases: [
    { title: 'Implementar', detail: 'A (núcleo) y B (descriptor e interfaz) en paralelo, en worktrees aisladas' },
  ],
}

const COMMON = `
Proyecto «Victoria II Mod Studio» (Python 3.10+, PySide6 ≥ 6.5, numpy, Pillow). Trabajas en una worktree aislada de
git: haz TODO tu trabajo en ella (tu directorio actual) y haz commits en su rama. No toques el repositorio principal
/home/user/VictoriaII_ModWizard ni ninguna otra worktree. Otro agente trabaja en paralelo en archivos disjuntos de
los tuyos (la lista de cada uno está abajo): no edites archivos que no sean tuyos; si necesitas algo de un archivo
ajeno, dilo en tu informe final (el orquestador lo integra).

EN PARALELO, el orquestador corrige en la rama principal los hallazgos de la revisión de la iteración 1 en
ui/pages/project_page.py (barra de estado, ficha), ui/viewers/{clausewitz_viewer,image_viewer,common,
validation_panel}.py, ui/pages/localisation_page.py, ui/tasks.py, core/encoding.py (un mapa de nombres de
codificación para mostrar), core/clausewitz/parser.py y core/csvloc/lint.py. Toca esos archivos solo lo
imprescindible y en otras zonas (la integración se hará con fusión de tres vías).

LEE ANTES DE EMPEZAR (en tu worktree):
- CONTINUAR_EN_CLAUDE_CODE.md §1–§3 (qué es, decisiones, qué hay) y §5 «Método de trabajo».
- docs/diseno/wizard.md: §0, §1 (D1–D19), §3 (invariantes I1–I12), §4 (reglas de dependencia y de escritura),
  §5, §6, §13.1–13.3, §14.1, §19.1–19.2, §19.5, §20, §21, §22 «Iteración 2» (entregables y los 11 criterios de
  aceptación) y §24 (decisiones del usuario, que mandan).
- El commit de contrato (git show HEAD --stat y git show HEAD): firmas, dataclasses y docstrings que tienes que
  respetar. Puedes AÑADIR funciones o parámetros opcionales; no cambies las firmas del contrato sin una razón que
  expliques en tu informe.

CONVENCIONES (obligatorias):
- Identificadores en inglés; docstrings y comentarios en español, concisos, en el estilo del código que hay.
- Núcleo (vic2studio.core) sin Qt. Todo texto visible por tr() con paridad ES/EN (tests/test_i18n.py).
- Compatible con Python 3.10 (nada de TestCase.enterContext, tomllib, ExceptionGroup, typing.Self…) y con la API de
  Qt 6.5. Comprueba la sintaxis con ast.parse(src, feature_version=(3, 10)).
- Pruebas con unittest. Cada prueba que añadas para un comportamiento debe fallar si quitas ese comportamiento
  (haz la mutación y compruébalo en los casos importantes).
- Escrituras en disco: solo core/fileio.py contiene primitivas crudas; dentro del mod solo escribe
  core/project/journal.py tras WriteGuard.check (wizard §4). Las pruebas (tests/) sí pueden escribir directamente.
- No subas ni generes datos del juego de Paradox. No hay corpus en esta máquina: usa tests/fixtures/shago_mod_min,
  tests/_layers.py y el minijuego sintético.

ENTORNO:
- QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" python3 -m unittest discover -s tests
  (Python 3.13 + PySide6 6.12). Python 3.10.20 + PySide6 6.11.3: /tmp/py310/bin/python.
- La máquina tiene 4 CPU compartidas con el otro agente: las pruebas de latido (mayor hueco del hilo de la
  interfaz) pueden fallar por carga. Repítelas solas antes de darlas por rotas.
- Usa directorios temporales propios para todo lo que escriban tus pruebas.

AL TERMINAR:
- La batería COMPLETA en verde con Python 3.13 (y tus pruebas nuevas también con /tmp/py310/bin/python).
- Commits en tu rama con mensajes en español que resumen el cambio y las pruebas, terminados con:
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_012bUbBLi474RPKRFu1VgDgL
- Devuelve: rama y hash del último commit, lista de archivos, qué criterios de aceptación cubre cada prueba, qué
  quedó sin hacer o dudoso, y qué necesitas del otro agente o del orquestador.
`

const AGENT_A = `${COMMON}
ERES EL AGENTE A (NÚCLEO). Tus archivos (solo estos):
core/encoding.py, core/clausewitz/{lexer,serializer,nodes}.py, core/csvloc/serialization.py, core/fileio.py,
core/vfs/** , core/project/** (incluido core/project/texts/project.{es,en}.json), core/appdirs.py, core/texts.py,
tests/_layers.py (ya está en el contrato; puedes ampliarlo), tests/_minigame.py y las pruebas
tests/test_{lexer_cr,vfs_*,project_*,journal_*,undo_*,arch_writes,noop_save,fileio_journal,appdirs,texts}.py.

QUÉ IMPLEMENTAR (wizard §22, iteración 2, agente A):
1. Arreglo CR: ya está (test_clausewitz_parser.LineBreakTests.test_cr_only_files, test_encoding
   test_cr_only_newlines). Solo añade test_lexer_cr.py con el criterio 2 literal: parse("a = 1 # c\\rb = 2\\r") da
   2 entradas en las líneas 1 y 2, y detect_newline devuelve "\\r".
2. core/fileio.py: stage_bytes, commit_staged (reintentos ante PermissionError), discard_staged, fsync_dir,
   copy_file, move_file, remove_file, make_dirs, remove_empty_dirs; atomic_write_bytes reimplementada encima con la
   MISMA firma y comportamiento (sus pruebas actuales deben seguir pasando).
3. serializer.render_checked y csvloc.render_csv_checked extraídas de write_file / write_csv_file sin cambiar su
   comportamiento (las pruebas actuales lo vigilan).
4. core/vfs: VPath, windows_name_problems, long_path_problem, Fingerprint, VfsSnapshot, LOAD_RULES (la tabla de
   wizard §5.2 completa, con tag_key y leading_int_key), rule_for, WriteGuard (realpath; enlaces simbólicos que
   salen; '..'; mayúsculas; mod dentro del juego; descriptor admitido; extra_roots) y VirtualFS (scan, resolve, stack,
   list, mod_target con la mayúscula de las carpetas existentes, replace_path recursivo y no, snapshot, refresh,
   case_collisions, same_as_game, dependencias). DESCRIPTOR_REL es la ruta reservada del descriptor (.mod, fuera
   de la carpeta del mod): resolve/stack/read_bytes/mod_target la tratan como un archivo de la capa MOD.
5. core/project: codecs (Clausewitz, Localisation, Binary), documents (LRU), undo (instantáneas zlib, fusión por
   merge_key, límites), workspace (open sin escribir, transacciones anidadas que se funden y que revierten si
   lanzan, touch, replace_model, replace_text con D17, create, delete, undo/redo exactos, dirty por versión,
   changeset con diff, save con el diario, revert, check_external_changes, reload, accept_external, external_diff,
   write_recovery, subscribe, bind_to_current_thread, WrongThreadError), journal (SaveTransaction con los pasos de
   §6.5, .bak, originals/, papelera, FAULT_HOOK), recovery (pending_journals, recover idempotente, orphan_sessions,
   load_session), lock (pid caducado), settings (project.json sin crearlo al leer), diffing y project (Project.open:
   descriptor, VFS, escaneo, bloqueo, recuperación; edit, save, set_settings, restore_session, close).
   Los textos de SaveProblem van en core/project/texts/project.{es,en}.json (clave "project.<código>").
6. core/appdirs.py (VIC2STUDIO_DATA_DIR / VIC2STUDIO_CACHE_DIR) y core/texts.py.
7. tests/_minigame.py mínimo (wizard §19.1, lo que necesita esta iteración): juego sintético con
   common/cb_types.txt (peace_order y 2-3 CB con months), common/countries.txt (con dynamic_tags), localisation,
   history/provinces con un archivo solo CR y nombre irregular, events/, y un mod vacío o con archivos.
8. Pruebas por riesgo (§19.2) de esta iteración: test_vfs_guard (I1: enlaces que escapan, '..', '\\\\',
   mayúsculas, mod dentro del juego, descriptor), test_vfs_resolution (WHOLE_FILE, UNION, KEYED, replace_path
   recursivo y no, mayúsculas, dependencias), test_journal_commit, test_journal_crash (fallo inyectado en CADA paso
   de un guardado de 3 archivos y PermissionError en el tercer os.replace: tras recover() todo antes o todo después;
   recuperar dos veces da lo mismo), test_journal_kill (subproceso con os._exit en el paso k), test_noop_save
   (guardar sin cambios no escribe ni crea .vic2studio/: árbol y mtimes idénticos), test_workspace_readonly (abrir
   y leer no escribe), test_undo_property (secuencias aleatorias con semilla fija sobre el minijuego: deshacer todo
   da los bytes originales; rehacer todo, los del avance), test_workspace_thread, test_project_open,
   test_lock, test_external_change, test_recovery_autosave y test_arch_writes (recorrido AST de src/: ninguna
   primitiva cruda fuera de core/fileio.py; llamadas a fileio solo desde journal, lock, los envoltorios
   serializer.write_file y csvloc.write_csv_file, y las excepciones declaradas y justificadas en la propia prueba:
   ui/theme.py, las CLI, settings.py; y core/modfile.py solo si sigue escribiendo directamente, cosa que el agente B
   debe quitar: escribe la prueba de modo que la lista de excepciones sea explícita).
   Criterio 3 con el minijuego: cambiar months de un CB y guardar crea solo <mod>/common/cb_types.txt, con un
   diff de 1 línea respecto al del juego, y los hashes del juego no cambian. Con un mod que ya tiene su copia, el
   mismo cambio la modifica con un diff de 1 línea. Criterio 7: deshacer y rehacer una transacción de 3 archivos es
   exacto byte a byte; deshacer hasta el punto guardado deja el documento limpio.
`

const AGENT_B = `${COMMON}
ERES EL AGENTE B (DESCRIPTOR E INTERFAZ). Tus archivos (solo estos):
core/modfile.py, core/modcheck.py (solo los textos MESSAGES de los códigos nuevos del descriptor),
ui/session.py, ui/main_window.py, ui/pages/__init__.py, ui/pages/project_page.py (solo lo imprescindible para
integrarla como sección «Archivos»), ui/pages/localisation_page.py (solo lo imprescindible para vivir en la sala
Textos), ui/pages/planned.py, ui/pages/{map,countries,events}_page.py (retirarlas o adaptarlas), ui/shell/**,
ui/halls/** , ui/dialogs/**, ui/widgets/layer_badge.py, ui/widgets/icons_extra/**, i18n/__init__.py,
i18n/es.json, i18n/en.json, i18n/{es,en}/*.json, pyproject.toml, tools/screenshot.py, tests/_fake_project.py y
las pruebas tests/test_{modfile_write,ui_shell,ui_descriptor,ui_new_mod,ui_session,ui_smoke,ui_roadmap}.py; además
puedes adaptar test_ui_pages.py, test_ui_integration.py, test_ui_localisation.py y test_i18n.py SOLO donde dependan
de la navegación de 5 páginas (cada adaptación, justificada en tu informe; nunca para debilitar lo que comprueban).

QUÉ IMPLEMENTAR (wizard §22, iteración 2, agente B):
1. core/modfile.py (wizard §14.1 y el contrato): DescriptorSpec, render_descriptor (con y sin existente: conserva
   comentarios y claves desconocidas; UTF-16 → cp1252), descriptor_problems (reutiliza modcheck.check_descriptor y
   añade los códigos nuevos con sus textos en modcheck.MESSAGES), create_mod_skeleton (una transacción del diario
   de core/project/journal: el agente A lo implementa; hasta entonces tus pruebas de escritura se marcan
   skipUnless(implementado)), sanitize_folder, y write_descriptor reescrita sobre render_descriptor y el diario
   (misma firma y comportamiento; sus pruebas actuales deben pasar) para que modfile no escriba directamente.
   Prueba de oro (criterio 8): render_descriptor(DescriptorSpec("Shago Mod", "VSM", "VSM")) == bytes de
   tests/fixtures/shago_mod_min/VSM.mod; «Dark Age Mod» con carpeta DAM da path = "mod/DAM" y user_dir = "DAM" en
   cp1252 con CRLF; sanitize_folder("Dark Age Mod") propone DAM y Dark_Age_Mod.
2. ui/session.py según el contrato (único puente con Qt; abrir en segundo plano con ui.tasks.TaskRunner y
   Workspace.bind_to_current_thread al recibir el proyecto en el hilo de la interfaz).
3. Armazón de 7 salas (wizard §13.1–13.2): ui/halls/registry.discover_halls, un paquete por sala en ui/halls/<sala>/
   con HALL y SECTIONS, ui/shell/hall.py (HallPage con SectionRail de madera y QStackedWidget), section_rail.py,
   pending_changes.py (panel «Cambios pendientes» con el ChangeSet y su diff), history_dock.py (Historial de
   deshacer). Las secciones que aún no existen se ven como tarjeta «en desarrollo» con su iteración (wizard §22:
   Mapa 5, Naciones 6 —Culturas y Gobiernos 4—, Guerra 6 —CB, bookmarks y unidades 4—, Eventos 7, Interfaz 8,
   Taller de mapas 9, Textos editables 3, Validación 3). La hoja de ruta (RoadmapStrip con los 10 hitos) pasa a
   Inicio. MainWindow: placas cortas Proyecto · Mapa · Naciones · Guerra · Eventos · Interfaz · Textos (caben a
   1100 px), Ctrl+1..7, Ctrl+S/Z/Y (y Ctrl+Mayús+Z), contador de cambios en «Guardar (N)», título con «*» si hay
   cambios, y closeEvent que pregunta si hay cambios sin guardar y escribe la recuperación.
   COMPATIBILIDAD: MainWindow.page("project") debe seguir devolviendo la ProjectPage (ahora sección «Archivos»
   de la sala Proyecto) y page("localisation") la LocalisationPage (sala Textos), con sus señales y API actuales,
   porque test_ui_pages, test_ui_integration, test_ui_localisation, test_ui_viewer y tools/screenshot.py las usan.
   Hoy dependen de la navegación de 5 páginas: test_ui_smoke (43 puntos), test_ui_localisation (14),
   test_ui_integration (10), test_ui_pages (8), test_i18n (4) y test_ui_roadmap (3).
4. Sala Proyecto: Inicio (wizard §13.3: carpeta del juego validada con evaluate_game, tarjetas de los
   <juego>/mod/*.mod con read_descriptor y «Crear mod nuevo», «¿Qué quieres hacer?» con las tarjetas de flujos que
   indican su iteración, y la hoja de ruta), Descriptor .mod (formulario sobre DescriptorSpec que edita el .mod con
   Session.edit → Workspace con DESCRIPTOR_REL, con sugerencia de carpeta, selector de replace_path con el efecto
   explicado y los problemas de descriptor_problems), Archivos (la ProjectPage actual con insignias de capa
   J / M / M⊃J en el explorador: ui/widgets/layer_badge.py) y Cambios pendientes.
5. Diálogos ui/dialogs/{save_review,conflict,recovery,new_mod}.py: revisión antes de guardar solo si hay copias
   del juego base, papelera, conflictos o errores (D13); conflicto con «Conservar mis cambios» (accept_external),
   «Recargar del disco» (reload) y «Comparar» (external_diff); recuperación (Project.recovered y orphan_sessions,
   con restore_session); Nuevo mod (nombre, carpeta sugerida, user_dir, plantilla opcional; create_mod_skeleton).
6. i18n por fragmentos (wizard §21): load_catalog(code) combina es.json con i18n/es/*.json y los textos del núcleo
   (core.texts.load_texts), y lanza error ante claves duplicadas; tus textos nuevos en i18n/{es,en}/{shell,project}.json;
   pyproject.toml amplía package-data con i18n/*/*.json y core/**/texts/*.json.
7. tools/screenshot.py: --hall, --section y --no-game-art (por defecto en docs/capturas), sin romper las opciones
   actuales.
8. Trabaja contra el contrato con un Project falso (tests/_fake_project.py, sobre tests/_layers.py) hasta la
   integración: las pruebas que necesitan el núcleo real se marcan skipUnless(implemented(...)) con un motivo
   claro. Criterio 10: capturas ES/EN a 1100x700 y 1920x1080 de Inicio, Descriptor .mod, Archivos y el diálogo de
   revisión, sin textos cortados ni claves crudas: genéralas con tu tools/screenshot.py en una carpeta temporal y
   MÍRALAS con la herramienta Read; corrige lo que veas.
`

const SUMMARY = {
  type: 'object',
  properties: {
    branch: { type: 'string' },
    commit: { type: 'string' },
    worktree: { type: 'string', description: 'ruta absoluta de tu worktree' },
    files: { type: 'array', items: { type: 'string' } },
    criteria: { type: 'string', description: 'qué criterios de aceptación cubre cada prueba' },
    tests: { type: 'string', description: 'resultado real de la batería completa (Ran N ... OK) en 3.13 y de tus pruebas en 3.10' },
    contract_changes: { type: 'string', description: 'cambios a firmas del contrato y por qué' },
    pending: { type: 'string', description: 'qué quedó sin hacer, dudoso o skipUnless' },
    needs: { type: 'string', description: 'qué necesitas del otro agente o del orquestador' },
  },
  required: ['branch', 'commit', 'worktree', 'files', 'criteria', 'tests', 'pending', 'needs'],
}

phase('Implementar')
const [a, b] = await parallel([
  () => agent(AGENT_A, { label: 'agente-A:núcleo', phase: 'Implementar', isolation: 'worktree', schema: SUMMARY }),
  () => agent(AGENT_B, { label: 'agente-B:interfaz', phase: 'Implementar', isolation: 'worktree', schema: SUMMARY }),
])
return { a, b }

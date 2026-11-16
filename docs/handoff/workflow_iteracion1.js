export const meta = {
  name: 'vic2-mod-studio-iter1',
  description: 'Victoria II Mod Studio iteración 1: parser Clausewitz, CSV, UI con estética Vic2, docs; verificación adversarial y corrección',
  phases: [
    { title: 'Build', detail: 'parser, csv, ui shell, docs en paralelo' },
    { title: 'Integrate', detail: 'conectar parser y CSV a la UI' },
    { title: 'Verify', detail: 'verificadores adversariales por componente' },
    { title: 'Fix', detail: 'corregir hallazgos y re-verificar' },
  ],
}

const P = '<carpeta del repositorio>'
const SCRATCH = '<carpeta temporal de la sesión>'
const TEMPLATE = '<carpeta de la plantilla>'
const ZIPCORPUS = SCRATCH + '/corpus'
const CORPUS_ENV = 'VIC2_CORPUS="' + TEMPLATE + ':' + ZIPCORPUS + '"'
const TEST_CMD = 'cd ' + P + ' && ' + CORPUS_ENV + ' QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v'

const COMMON = `
CONTEXTO DEL PROYECTO
Estamos construyendo "Victoria II Mod Studio": app de escritorio (Windows + Linux) para crear/editar mods de Victoria II (motor Clausewitz de Paradox) de forma visual. Stack decidido: Python 3 + PySide6 (Qt 6) + numpy + Pillow. NO hay Rust ni red garantizada: usa SOLO stdlib + PySide6 (6.11 instalado) + numpy + Pillow. No instales nada con pip en el sistema.
Este es el primer entregable (iteración 1): arquitectura, árbol de directorios, motor de parseo (Clausewitz .txt <-> JSON y CSV <-> JSON) y prototipo de la ventana principal con estética Victoria II, selector de idioma ES/EN en tiempo real y navegación entre los 5 módulos.

RUTAS
- Raíz del proyecto: ${P}
- Código: ${P}/src/vic2studio/   (paquete "vic2studio", layout src)
- Pruebas: ${P}/tests/  (unittest de stdlib; cada archivo de prueba hace sys.path.insert(0, <raiz>/src) como tests/test_encoding.py)
- Corpus real de SOLO LECTURA (nunca lo modifiques): "${TEMPLATE}" (mod plantilla: ~3900 .txt, 22 .csv, 1 .lua, gfx) y ${ZIPCORPUS}/VSM (+ ${ZIPCORPUS}/VSM.mod), los archivos de texto del mod del usuario "Shago Mod". En el corpus del usuario hay DOS archivos con errores reales de llaves: VSM/decisions/somaliland_shago.txt y VSM/decisions/zulu_expancionshago.txt (a ambos les falta la llave de cierre del bloque political_decisions abierto en la línea 1).
- Scratchpad para scripts temporales, capturas y salidas: ${SCRATCH}  (no dejes scripts de usar y tirar dentro del proyecto).
- Comando de pruebas completo: ${TEST_CMD}

YA EXISTE (escrito por el arquitecto; léelo antes y reutilízalo, no lo reescribas salvo bug real):
- src/vic2studio/__init__.py (__version__, APP_NAME, ORG_NAME)
- src/vic2studio/core/__init__.py
- src/vic2studio/core/encoding.py: decode_bytes(data, encoding=None)->DecodedText(text, encoding) [BOM utf-8 -> utf-8-sig; no-ASCII y UTF-8 válido -> utf-8; si no cp1252 sin pérdidas], encode_text(text, encoding) [lanza UnencodableTextError con .problems=(indice,linea,col,char)], find_unencodable, detect_newline, GAME_ENCODING='cp1252'.
- src/vic2studio/core/fileio.py: read_text(path)->DecodedText, atomic_write_bytes(path, data, backup=False), write_text(path, text, encoding, backup=False).
- tests/_corpus.py: corpus_roots(), corpus_files(suffixes) leyendo la variable VIC2_CORPUS; CLAUSEWITZ_SUFFIXES.
- tests/test_encoding.py (pasa: los 7882 archivos de texto del corpus hacen ida y vuelta byte a byte).

REGLAS
- Sintaxis compatible con Python 3.10+ (nada de "type X =", genéricos PEP 695, etc.). Puedes comprobarlo con ast.parse(src, feature_version=(3, 10)).
- Identificadores en inglés; docstrings y comentarios en español, con la densidad y el estilo de encoding.py / fileio.py (concisos, sin comentarios obvios).
- No toques archivos de otros componentes salvo que tu tarea lo diga. No modifiques nada fuera de ${P} excepto el scratchpad.
- Sé riguroso: ejecuta de verdad tu código y tus pruebas, no declares que algo funciona sin haberlo ejecutado.
`

const PARSER_CONTRACT = `
CONTRATO PÚBLICO DEL PARSER CLAUSEWITZ (paquete vic2studio.core.clausewitz; la UI depende de estos nombres exactos)
from vic2studio.core.clausewitz import (parse, parse_file, write_file, to_source, format_canonical, to_json, from_json, simplify, walk,
    ParseResult, Document, Block, Entry, Scalar, ClausewitzDate, Diagnostic, Severity)
- parse(text: str, *, filename: str | None = None) -> ParseResult
- parse_file(path, *, encoding: str | None = None) -> ParseResult   (usa core.fileio.read_text / encoding.decode_bytes; detecta newline con detect_newline)
- ParseResult: .document (Document), .diagnostics (list[Diagnostic]), .encoding (str), .newline (str), .path (Path|None), propiedades .ok (sin errores), .errors, .warnings
- Diagnostic: .code (str), .severity (Severity.ERROR / WARNING / INFO, Enum), .line y .column (1-based), .offset (índice en el texto), .args (dict), .related (list de (line, column) relacionados, p.ej. dónde se abrió un bloque), método .message(lang: str = "en") -> str con tablas "es" y "en" completas para TODOS los códigos.
  Códigos mínimos: unclosed_block (args: key, open_line), unexpected_close_brace, missing_value (clave = sin valor antes de } o EOF), missing_key (operador sin clave), unterminated_string, invalid_key (un bloque usado como clave, p.ej. "{ a } = b"). Puedes añadir más si los justificas.
- Scalar(text: str, quoted: bool = False): .text (texto crudo, sin comillas), .quoted, as_int(), as_float(), as_bool() (yes/no -> True/False; otro -> ValueError), as_date() -> ClausewitzDate, is_number(), is_date(); str(scalar) == text.
- ClausewitzDate(year, month=1, day=1): parse("1861.1.1"), str() -> "1861.1.1", comparable/ordenable.
- Entry: .key (Scalar | None; None para valores sueltos como los de "{ 1 2 3 }"), .op (str | None: "=", "<", ">", "<=", ">=", "!=", "=="), .value (Scalar | Block), .line, .column; .is_assignment
- Block: .entries (list[Entry]), __iter__ (sobre entries), __len__, get(key, default=None) -> primer valor, get_all(key) -> list, get_text(key, default=None) -> texto del primer escalar, has(key), find(key) -> Entry|None, find_all(key), keys() (orden de aparición, sin repetidos), values() (valores sueltos), set(key, value) (reemplaza el valor de la primera entrada con esa clave conservando su formato; si no existe, append), append(key, value, op="=") -> Entry, append_value(value) -> Entry, insert(index, key, value, op="=") -> Entry, remove(key) -> int (elimina todas las entradas con esa clave), remove_entry(entry). Todas las búsquedas por clave admiten ignore_case=False. Los "value" aceptados en set/append/insert: Scalar, Block, str (sin comillas si es una palabra válida sin espacios ni caracteres especiales; si no, entre comillas), int, float, bool (-> yes/no), ClausewitzDate, list (-> Block de valores sueltos), dict (-> Block de asignaciones).
- Document(Block): bloque raíz; .newline.
- to_source(document) -> str: reproduce EXACTAMENTE el texto original si no hubo ediciones (incluidos comentarios, espacios, tabs, CRLF, y también en archivos con errores de sintaxis); con ediciones, solo cambia lo editado.
- write_file(path, document_or_result, *, encoding=None, backup=True): to_source + fileio.write_text (atómico). encoding por defecto: la detectada al leer (o cp1252 si el documento se creó desde cero).
- format_canonical(node, *, indent="\\t", newline="\\n") -> str: impresión bonita normalizada ("clave = valor", bloques indentados, listas cortas de escalares en línea "{ 1 2 3 }", comentarios opcionales).
- to_json(node, *, include_comments=False) -> dict JSON-serializable con este esquema EXACTO:
    bloque/documento: {"type": "block", "entries": [entrada, ...]}
    entrada: {"key": escalar | null, "op": "=" | ... | null, "value": escalar | bloque}   (+ "comments": [ "# ..." ] si include_comments y la entrada tiene comentarios antes)
    escalar: {"type": "scalar", "text": "GEL", "quoted": false}
- from_json(obj) -> Document (formato canónico). Invariante: to_json(parse(format_canonical(from_json(to_json(doc)))).document) == to_json(doc).
- simplify(node): vista con pérdidas para lectura rápida: bloque solo con valores sueltos -> list; con asignaciones -> dict (claves repetidas -> list en orden); escalares numéricos -> int/float, yes/no -> bool, el resto str.
- walk(node) -> iterador de (path: tuple[str, ...], entry) en profundidad.
- CLI: python -m vic2studio.core.clausewitz check RUTA... [--lang es|en]  (recorre archivos y carpetas, imprime "archivo:línea:columna: severidad: mensaje", código de salida 1 si hay errores) y python -m vic2studio.core.clausewitz tojson ARCHIVO [--comments].
`

const CSV_CONTRACT = `
CONTRATO PÚBLICO DEL MÓDULO DE LOCALIZACIÓN CSV (paquete vic2studio.core.csvloc; la UI depende de estos nombres exactos)
from vic2studio.core.csvloc import (parse_csv, read_csv_file, write_csv_file, to_source, to_json, from_json,
    LocalisationFile, LocRow, RowKind, CsvDiagnostic, LocalisationDB, LANGUAGE_COLUMNS, LANGUAGE_CODES, END_MARKER)
Formato de Victoria II: una entrada por línea, campos separados por ";" (el juego NO usa un CSV estándar), columna 0 = clave, columnas 1..13 = idiomas, columna 14 = marcador de fin "x"; tras la "x" puede haber campos extra vacíos que hay que conservar (en vanilla aparece "...;;;;;x;;;;"). Líneas que empiezan por "#" son comentarios. Codificación cp1252.
- LANGUAGE_COLUMNS = ["English","French","German","Polish","Spanish","Italian","Swedish","Czech","Hungarian","Dutch","Portuguese","Russian","Finnish"] (columna i+1); LANGUAGE_CODES = {"en":1,"fr":2,"de":3,"pl":4,"es":5,"it":6,"sv":7,"cs":8,"hu":9,"nl":10,"pt":11,"ru":12,"fi":13}; END_MARKER = "x". Documenta que el juego vanilla solo muestra English, French, German y Spanish.
- RowKind Enum: DATA, COMMENT, BLANK.
- LocRow: .kind, .key, .fields (list[str] crudos: todas las columnas tras la clave, incluida la "x" y extras), .line (1-based), .raw (texto original de la línea sin el salto), get(lang) (lang = código "es" o nombre "Spanish" o índice de columna) -> str ("" si no existe), set(lang, text) (rellena columnas que falten), .has_end_marker, .modified.
- LocalisationFile: .rows, .encoding, .newline, .path, .diagnostics (list[CsvDiagnostic]), .trailing_newline (bool), keys(), get_row(key) -> primera LocRow con esa clave, get(key, lang), set(key, lang, text) (crea la fila si no existe: "key;...;x" con 13 columnas de idioma + x), add_row(key, texts: dict), remove_row(key) -> int, lint() -> list[CsvDiagnostic].
- parse_csv(text, *, filename=None) -> LocalisationFile; read_csv_file(path, *, encoding=None) -> LocalisationFile; to_source(file) -> str (EXACTO byte a byte tras codificar si no hay ediciones; las filas editadas se re-serializan como clave;13 columnas;x conservando los extras tras la x); write_csv_file(path, file, *, encoding=None, backup=True) (atómico vía core.fileio).
- CsvDiagnostic: .code, .severity (reutiliza vic2studio.core.clausewitz.Severity SI existe en el momento de integrar; para no depender del orden de construcción, define tu propio Enum Severity con miembros ERROR/WARNING/INFO en csvloc y expórtalo también como csvloc.Severity), .line, .column, .args, .message(lang="en") con tablas "es"/"en" completas.
  Códigos mínimos: missing_end_marker (fila sin la "x" en la columna 14), too_few_columns, duplicate_key (en el mismo archivo; el juego usa la primera), empty_key, semicolon_in_quotes (un campo con comillas que contiene ";": el juego no interpreta comillas, así que puede desplazar columnas; marcar como WARNING y verificar en el corpus vanilla si alguna vez aparecen comillas), unencodable_character (al validar para cp1252), header_row (INFO: fila de cabecera "key;English;...").
- to_json(file) -> {"encoding": ..., "newline": ..., "trailing_newline": bool, "rows": [{"kind":"data","key":...,"fields":[...]}, {"kind":"comment","text":...}, {"kind":"blank"}]}; from_json(obj) -> LocalisationFile; invariante: to_source(from_json(to_json(f))) == to_source(f) para archivos sin ediciones.
- LocalisationDB: from_dirs(dirs) carga *.csv de cada carpeta en orden alfabético de nombre de archivo; si dos carpetas tienen un archivo con el MISMO nombre, gana el de la primera carpeta (mod antes que vanilla); entre claves repetidas en distintos archivos gana la primera cargada (por eso los mods usan prefijos "00_"). lookup(key, lang="en") -> str|None, source_of(key) -> (path, line), overrides() -> lista de claves definidas más de una vez con quién gana, files.
- CLI: python -m vic2studio.core.csvloc check RUTA... [--lang es|en] y python -m vic2studio.core.csvloc tojson ARCHIVO.
`

const UI_CONTRACT = `
CONTRATO DE LA INTERFAZ (paquete vic2studio.ui + vic2studio.i18n + vic2studio.app)
- src/vic2studio/__main__.py -> from vic2studio.app import main; raise SystemExit(main())
- src/vic2studio/app.py: main(argv=None) -> int. Crea QApplication (organizationName=ORG_NAME, applicationName=APP_NAME), aplica el tema, crea MainWindow. Debe funcionar con QT_QPA_PLATFORM=offscreen.
- src/vic2studio/i18n/__init__.py: class Translator(QObject) con señal languageChanged(str); función translator() (singleton); tr(key, **fmt) -> str (clave desconocida -> devuelve la clave y registra un aviso una sola vez); set_language(code); language(); available_languages() -> [("es","Español"),("en","English")]. Archivos src/vic2studio/i18n/es.json y en.json (UTF-8, claves planas "nav.project", ...). Idioma inicial: el guardado en QSettings, si no el del sistema (es* -> es, si no en). Persistir con QSettings.
- src/vic2studio/ui/theme.py (+ style.qss si lo prefieres): paleta como constantes, apply_theme(app), texturas procedurales (pergamino, madera, terciopelo) generadas en tiempo de ejecución con QPainter/numpy y cacheadas. Carga cualquier .ttf/.otf de src/vic2studio/assets/fonts/ si existe (carpeta opcional) y si no usa una lista de serifas de reserva (p.ej. "Cinzel", "Cormorant Garamond", "EB Garamond", "Libre Baskerville", "Georgia", "Noto Serif", "DejaVu Serif", "Liberation Serif", serif). NO uses ni copies texturas, fuentes o imágenes del juego (copyright de Paradox): todo procedural.
- src/vic2studio/ui/widgets/: marcos ornamentados (doble borde bronce/dorado envejecido con remaches/esquinas), cabecera/estandarte, botones de navegación, iconos vectoriales dibujados con QPainter.
- src/vic2studio/ui/main_window.py: class MainWindow(QMainWindow): cabecera con título "Victoria II Mod Studio" + emblema + selector de idioma (Español/English) arriba a la derecha; barra de navegación con los 5 módulos; QStackedWidget con las páginas; barra de estado. Atajos Ctrl+1..Ctrl+5. Tamaño mínimo ~1100x700, recuerda geometría y última página en QSettings. API: pages (lista), current_page_index(), set_current_page(index), page(key) con key en ("project","map","countries","events","localisation").
- Los 5 módulos y sus páginas (src/vic2studio/ui/pages/):
  1 project_page.py  ProjectPage   "Proyecto y Archivos" (gestor de archivos y proyecto: rutas del juego base y del mod, explorador)
  2 map_page.py      MapPage       "Editor de Mapa"
  3 countries_page.py CountriesPage "Creador de Países"
  4 events_page.py   EventsPage    "Estudio de Eventos"
  5 localisation_page.py LocalisationPage "Localización (CSV)"
  Todas heredan de una base común (p.ej. pages/base.py BasePage con key, título, subtítulo, icono y retranslate()). Todas reaccionan a languageChanged re-traduciendo TODO texto visible sin reiniciar.
- Herramienta tools/screenshot.py (en ${P}/tools/): python3 tools/screenshot.py --out DIR [--lang es|en|all] [--page all|project|...] [--size 1440x900] [--mod RUTA] [--open-file RUTA] genera PNG nombrados <lang>_<n>_<page>.png con QT_QPA_PLATFORM=offscreen (procesando eventos/esperando a que carguen modelos asíncronos antes de capturar).
`

const BUILD_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    test_result: { type: 'string', description: 'salida resumida REAL de las pruebas ejecutadas' },
    known_limitations: { type: 'array', items: { type: 'string' } },
  },
  required: ['summary', 'files', 'test_result', 'known_limitations'],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['critical', 'major', 'minor'] },
          title: { type: 'string' },
          details: { type: 'string' },
          repro: { type: 'string', description: 'pasos o código mínimo para reproducir' },
          files: { type: 'array', items: { type: 'string' } },
        },
        required: ['severity', 'title', 'details', 'repro'],
      },
    },
    checks_passed: { type: 'array', items: { type: 'string' } },
    screenshots: { type: 'array', items: { type: 'string' } },
  },
  required: ['findings', 'checks_passed'],
}

const FIX_SCHEMA = {
  type: 'object',
  properties: {
    fixed: { type: 'array', items: { type: 'string' } },
    not_fixed: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, reason: { type: 'string' } }, required: ['title', 'reason'] } },
    test_result: { type: 'string' },
  },
  required: ['fixed', 'not_fixed', 'test_result'],
}

// ---------------------------------------------------------------- BUILD
phase('Build')

const parserBuild = () => agent(`${COMMON}
${PARSER_CONTRACT}
TU TAREA: implementar el motor de parseo Clausewitz completo en ${P}/src/vic2studio/core/clausewitz/ (p.ej. __init__.py, __main__.py, lexer.py, nodes.py, parser.py, serializer.py, json_bridge.py, diagnostics.py) y sus pruebas en ${P}/tests/test_clausewitz_*.py. Es la pieza más crítica del proyecto: el editor reescribirá archivos de mods reales y no puede perder ni corromper nada.

DISEÑO REQUERIDO
- Árbol de sintaxis concreto sin pérdidas: cada token guarda su "trivia" previa (espacios, saltos de línea, comentarios). Serializar un documento no editado concatena trivia+token y reproduce el texto exacto. Los nodos creados o editados por código generan formato coherente: indentación inferida de los hermanos (tabs o espacios según el archivo), salto de línea del documento (CRLF si el archivo es CRLF), la llave de cierre se queda en su línea.
- Lexer basado en una expresión regular maestra compilada (rendimiento). Tokens: "{", "}", operadores (=, <, >, <=, >=, !=, ==), cadenas entre comillas (pueden abarcar varias líneas; sin secuencias de escape: el contenido se guarda crudo), comentarios "#" hasta fin de línea (excepto dentro de comillas), y palabras sueltas: cualquier secuencia sin espacios ni { } = < > ! # " (incluye fechas 1861.1.1, negativos -0.5, nombres con . - ' : / y letras acentuadas). Ojo con casos como "a=b", "a={b}", "yes}", "}}", "= =", comentario pegado "x#c".
- Parser tolerante a errores con recuperación: nunca lanza excepción ante entradas arbitrarias (incluido texto binario o aleatorio), siempre devuelve un documento + diagnósticos, y to_source(documento) sigue reproduciendo el texto exacto incluso cuando hay errores (los tokens sobrantes se conservan como "basura" en el árbol para no perder bytes).
- Para unclosed_block informa la línea/columna donde se abrió el bloque y su clave (p.ej. "El bloque 'political_decisions' abierto en la línea 1 no se cierra"). Para los dos archivos rotos del usuario el diagnóstico debe señalar exactamente el bloque political_decisions de la línea 1.
- Las claves se comparan exactamente salvo ignore_case=True (el motor del juego suele ignorar mayúsculas: "Prestige" funciona).
- Los nodos exponen línea/columna (de su primer token) para que la UI pueda saltar a la posición.
- Sin dependencias de Qt.

PRUEBAS OBLIGATORIAS (unittest, que ejecutarás y harás pasar)
1. Corpus: TODOS los archivos con sufijo en tests/_corpus.CLAUSEWITZ_SUFFIXES de ambos corpus: (a) parse_file no lanza; (b) codificar to_source con la codificación detectada == bytes originales, para TODOS (también los que tengan errores); (c) solo los 2 archivos rotos del usuario tienen diagnósticos de error... salvo que encuentres errores reales en vanilla: en ese caso inspecciónalos a mano, decide si son errores genuinos del archivo (y lístalos explícitamente en la prueba como esperados, con el código y la línea) o un fallo del parser (y arréglalo); (d) invariante JSON del contrato para todos; (e) mide y registra el tiempo total (objetivo: corpus completo < 60 s en esta máquina; un archivo de 1 MB < 2 s).
2. Casos límite unitarios: todos los del lexer arriba, archivo vacío, solo comentarios, BOM, CRLF, tabs, bloques vacíos "{}", "{ }", bloques anónimos anidados "{ { a = b } { c = d } }", listas "color = { 97 209 251 }", claves fecha "1861.1.1 = { owner = GEL }", claves repetidas en orden (add_core), operadores de comparación, cadenas con #, { y saltos de línea dentro, comillas sin cerrar, llaves sobrantes, claves sin valor, = sin clave, bloque como clave.
3. API de edición: set de un escalar existente cambia solo ese token (comprueba con difflib que el resto del texto es idéntico); append en bloque con hermanos usa la indentación de los hermanos y queda antes de la llave de cierre; append en bloque vacío/en línea queda bien formado; remove no deja líneas en blanco sueltas; set con dict/list/bool/ClausewitzDate; documentos CRLF generan CRLF; editar y re-parsear da el árbol esperado sin diagnósticos.
4. Diagnósticos: líneas/columnas exactas y mensajes en es y en para cada código; la CLI check sobre los 2 archivos rotos del usuario devuelve código 1 y señala la línea 1.
5. Fuzzing ligero determinista (semilla fija): mutaciones aleatorias de bytes/tokens de archivos del corpus y secuencias aleatorias de tokens -> nunca excepción y to_source exacto.
Al terminar ejecuta el comando completo de pruebas (${TEST_CMD}) y reporta la salida real resumida.`, { label: 'build:parser', phase: 'Build', schema: BUILD_SCHEMA, effort: 'max' })

const csvBuild = () => agent(`${COMMON}
${CSV_CONTRACT}
TU TAREA: implementar el módulo de localización CSV completo en ${P}/src/vic2studio/core/csvloc/ (p.ej. __init__.py, __main__.py, model.py, io.py, diagnostics.py, db.py) y sus pruebas en ${P}/tests/test_csvloc_*.py. Sin dependencias de Qt.
Requisitos:
- Ida y vuelta sin pérdidas: to_source exacto para todos los .csv de ambos corpus (incluido localisation/text.csv de 3,6 MB y sus variantes), conservando CRLF/LF, ausencia o presencia de salto de línea final, líneas vacías, comentarios y campos tras la "x". Prueba también el .csv.bak como texto CSV.
- Estudia el corpus vanilla antes de diseñar: número de columnas reales por fila, si hay comillas, si hay ";" dentro de textos, filas sin "x", cabeceras, claves duplicadas dentro de un archivo y entre archivos. Los 3 archivos del usuario (VSM/localisation/00_VSM_*.csv) tienen filas SIN la "x" final y con cabecera "key;English;..." y en 00_VSM_decisions.csv hay campos entre comillas con ";" dentro: el lint debe detectarlo. Documenta en el docstring del módulo lo que encuentres.
- Rendimiento: leer text.csv (3,6 MB) < 1,5 s; LocalisationDB de toda la carpeta localisation < 5 s.
- Edición: set/add_row/remove_row y re-serialización correcta (fila nueva: "key;" + 13 columnas + "x"); filas editadas conservan los extras tras la x; detecta caracteres no codificables en cp1252 antes de escribir.
- Pruebas unittest: corpus ida y vuelta, invariante JSON, casos límite (línea solo con ";", clave vacía, filas cortas, comentarios con ";", BOM, último registro sin salto de línea, texto con "x" en medio), edición, DB (orden de carga, prioridad mod>vanilla, primera clave gana), CLI, mensajes es/en para todos los códigos.
Al terminar ejecuta el comando completo de pruebas (${TEST_CMD}) y reporta la salida real resumida (si fallan pruebas de OTROS componentes que aún se están construyendo en paralelo, indícalo pero no las toques).`, { label: 'build:csv', phase: 'Build', schema: BUILD_SCHEMA })

const uiBuild = () => agent(`${COMMON}
${UI_CONTRACT}
TU TAREA: construir el armazón de la interfaz (prototipo funcional de la ventana principal): app.py, __main__.py, i18n/ (Translator + es.json + en.json), ui/theme.py (+qss), ui/widgets/, ui/main_window.py, ui/pages/ (las 5 páginas), tools/screenshot.py y pruebas tests/test_ui_smoke.py + tests/test_i18n.py.
EN PARALELO otros agentes están escribiendo vic2studio.core.clausewitz y vic2studio.core.csvloc: NO los importes todavía (otro agente integrará el parser y el CSV en ProjectPage y LocalisationPage después). Deja puntos de extensión limpios:
- ProjectPage: grupo "Rutas" con ruta del juego base (Victoria II) y ruta del mod, cada una con botón "Examinar…" (QFileDialog), validación visual (indica si se encuentran common/, history/, localisation/, map/ etc. y si es un mod o el juego base) y persistencia en QSettings; explorador de archivos (QTreeView + QFileSystemModel enraizado en el mod) con filtro; panel de vista previa a la derecha (QSplitter) con un método set_preview_widget(widget) y una señal file_activated(Path) emitida al seleccionar un archivo. De momento la vista previa puede mostrar metadatos del archivo (nombre, tamaño, tipo).
- LocalisationPage: estructura con barra de herramientas (Abrir CSV…, buscador) y un área central intercambiable (set_central_widget) que de momento muestra un estado vacío elegante.
- MapPage, CountriesPage, EventsPage: tarjetas tipo pergamino "Módulo en desarrollo" con la lista de funcionalidades planificadas (traducidas ES/EN) tomadas del documento de requisitos: Mapa: lienzo con zoom/paneo que lee map/provinces.bmp, definition.csv y default.map; modos Político, Recursos (RGO), Infraestructura, Life Rating, Terreno; clic en provincia -> panel con owner, controller, add_core, trade_goods, life_rating, terrain, railroad, fort, naval_base, POPs; panel nacional (tecnologías, reformas, partido, upper_house, prestigio, pluralidad, economía/oob). Países: asistente paso a paso (TAG de 3 letras validado y registrado en common/countries.txt; color RGB e importador de imagen que genere las 5 banderas .tga TAG, _monarchy, _republic, _communist, _fascist en gfx/flags; common/countries/[Nombre].txt con partidos y nombres de unidades; history/countries/[TAG] - [Nombre].txt). Eventos: country_event/province_event; crear y editar los del juego base; ID, título, descripción, imagen; constructor de triggers AND/OR/NOT, fechas, tecnologías, variables; MTTH con modificadores; opciones con efectos y ai_chance. Indica en qué iteración llegará cada módulo (Mapa: iteración 3, Países: 4, Eventos: 5; Localización editable: 2; Proyecto/VFS y generador .mod: 2).
ESTÉTICA (crítico, el usuario lo pidió explícitamente): emular el estilo visual de Victoria II, siglo XIX victoriano/industrial: bordes de bronce/dorado envejecido, fondos de pergamino, terciopelo rojo oscuro, madera oscura, tipografía serif clásica (títulos con versalitas/espaciado), manteniendo usabilidad moderna: jerarquía clara, contraste de texto suficiente (tinta oscura sobre pergamino, crema sobre madera; apunta a WCAG AA), estados hover/pressed/checked/focus visibles, navegación por teclado, sin elementos que se rompan al redimensionar. Estiliza también QTreeView, QTableView, QLineEdit, QComboBox, QPushButton, QScrollBar, QSplitter, QToolTip, QMenu, QStatusBar, QTabWidget, QGroupBox, QHeaderView. Todo procedural (gradientes, ruido para la textura del pergamino, grano de madera, pequeñas ornamentaciones vectoriales); nada de recursos del juego.
I18N: TODO texto visible (incluidos tooltips, títulos de diálogos, barra de estado, placeholders) pasa por tr(); cambiar de idioma re-traduce la ventana entera al instante. tests/test_i18n.py: mismas claves en es.json y en.json, ningún valor vacío, todas las claves usadas en el código (búsqueda estática de tr("...")) existen. tests/test_ui_smoke.py (offscreen): crear MainWindow, recorrer las 5 páginas, Ctrl+1..5, cambiar idioma y comprobar que los textos de los widgets cambian (recorre widgets y compara textos antes/después), sin excepciones ni avisos Qt (instala qInstallMessageHandler y falla con avisos).
VERIFICA VISUALMENTE: genera capturas con tools/screenshot.py en ${SCRATCH}/screens/build/ para las 5 páginas en es y en, y MÍRALAS tú mismo con la herramienta Read (lee el PNG) e itera sobre el diseño hasta que se vea pulido y fiel a la estética pedida; incluye una con --mod "${TEMPLATE}". Reporta las rutas de las capturas finales en summary.
Al terminar ejecuta ${TEST_CMD} y reporta la salida real resumida (si fallan pruebas de otros componentes que se construyen en paralelo, indícalo sin tocarlas).`, { label: 'build:ui', phase: 'Build', schema: BUILD_SCHEMA })

const docsBuild = () => agent(`${COMMON}
${PARSER_CONTRACT}
${CSV_CONTRACT}
${UI_CONTRACT}
TU TAREA: documentación de arquitectura y empaquetado (no escribas código de la app; otros agentes lo están haciendo en paralelo con los contratos de arriba).
Archivos a crear en ${P}:
1. ARCHITECTURE.md (en español, claro y bien estructurado) con:
   a) Propuesta de arquitectura y stack: tabla comparativa PySide6/Qt6 vs Tauri+Rust/React vs Electron+React/TS (rendimiento del mapa, tamaño del ejecutable, empaquetado Windows/Linux, curva de aprendizaje, ecosistema, estado del entorno actual) y la decisión: Python + PySide6 + numpy + Pillow. Explica con honestidad que se había recomendado Tauri inicialmente y que se cambió porque en esta máquina no hay toolchain de Rust ni webkit2gtk-4.1, mientras que PySide6 6.11 y numpy ya están instalados, lo que permite probar todo ahora mismo; y por qué el rendimiento del mapa no es un problema en Python: provinces.bmp de vanilla (5616x2160, 24 bits) se lee con Pillow a un array numpy; se empaqueta RGB en uint32, se mapea a ID de provincia con definition.csv (np.unique + searchsorted o tabla) -> ráster uint16; cada modo de mapa es una LUT (N+1,3) uint8 y la imagen es lut[raster] (operación vectorizada de decenas de ms); fronteras por comparación de rásteres desplazados; picking de clic = raster[y, x]; visualización con QGraphicsView/QPixmap con zoom/paneo y, si hiciera falta, QOpenGLWidget con un shader que resuelve la LUT en GPU para cambio de modo instantáneo. Menciona default.map (max_provinces, sea_starts, nombres de archivos) y terrain.bmp (8 bits indexado).
   b) Arquitectura por capas: core (sin Qt: encoding, fileio, clausewitz, csvloc; planificado: vfs, model de dominio, validadores, map), services (planificado: proyecto, índice de símbolos, deshacer/rehacer), ui (Qt). Diagrama ASCII o mermaid de dependencias y flujo de datos (archivo -> parser -> árbol CST -> modelo/JSON -> formularios -> edición -> serializador sin pérdidas -> escritura atómica en la carpeta del mod).
   c) Sistema de herencia Vanilla + Mod (VFS): el juego base es solo lectura, toda escritura va a la carpeta del mod creando subcarpetas (common/, history/, events/, map/, localisation/, decisions/, gfx/), semántica de replace_path del .mod, resolución de un archivo (mod sobre vanilla), y el generador del descriptor .mod (name, path, user_dir, replace_path).
   d) Motor de parseo: CST sin pérdidas con trivia, tolerancia a errores y diagnósticos con códigos y mensajes ES/EN, API de edición que conserva formato, esquema JSON exacto del contrato, simplify, CLI check/tojson; política de codificación (cp1252 sin pérdidas, UTF-8 detectado, escritura atómica con .bak); formato CSV de Vic2 (columnas, "x", primera clave gana, prefijos 00_, idiomas que muestra el juego).
   e) Árbol de directorios COMPLETO del proyecto: lo implementado en esta iteración (según los contratos) y lo planificado marcado "(planificado)", con una línea de descripción por archivo/carpeta.
   f) Hoja de ruta por iteraciones: 1 (esta: arquitectura, parser, CSV, ventana principal), 2 (VFS vanilla+mod, generador .mod, editor de localización editable con sincronización de claves, validador global del mod), 3 (editor de mapa y modos), 4 (asistente de países con banderas .tga), 5 (estudio de eventos y decisiones), 6 (empaquetado y pulido). Riesgos y mitigaciones (corrupción de archivos, codificación, rendimiento, fidelidad del parser).
   g) Estrategia de pruebas: unittest, corpus real de ida y vuelta byte a byte, fuzzing, pruebas de UI offscreen, capturas.
2. README.md (en español, con una sección breve en inglés): qué es, requisitos (Python 3.10+, PySide6, numpy, Pillow), cómo ejecutar desde el código (PYTHONPATH=src python3 -m vic2studio, o pip install -e . y el comando vic2studio), cómo ejecutar las pruebas (incluida la variable VIC2_CORPUS), uso de las CLI check/tojson del parser y del CSV (p.ej. para detectar llaves sin cerrar en un mod), y estado del proyecto.
3. pyproject.toml (setuptools, layout src, nombre vic2studio, versión dinámica o 0.1.0, requires-python >=3.10, dependencias PySide6>=6.5, numpy>=1.24, Pillow>=10, [project.gui-scripts] vic2studio = "vic2studio.app:main", package-data para i18n/*.json, ui/*.qss y assets/**). Valídalo con tomllib.
4. requirements.txt.
5. packaging/: vic2studio.spec de PyInstaller (one-folder, incluye datos i18n/qss/assets, nombre "Victoria II Mod Studio"), build_linux.sh, build_windows.bat, linux/vic2studio.desktop. No hace falta ejecutar PyInstaller (no está instalado), pero que las rutas sean coherentes con el layout.
Al final revisa que todo lo que afirmas sea coherente con los contratos y con los archivos que ya existen.`, { label: 'build:docs', phase: 'Build', schema: BUILD_SCHEMA })

const [parserR, csvR, uiR, docsR] = await parallel([parserBuild, csvBuild, uiBuild, docsBuild])
log('Build terminado: parser=' + !!parserR + ' csv=' + !!csvR + ' ui=' + !!uiR + ' docs=' + !!docsR)

// ---------------------------------------------------------------- INTEGRATE
phase('Integrate')
const integ = await agent(`${COMMON}
${PARSER_CONTRACT}
${CSV_CONTRACT}
${UI_CONTRACT}
Los componentes ya están construidos. Resúmenes de los constructores (pueden contener limitaciones que debes tener en cuenta):
PARSER: ${JSON.stringify(parserR)}
CSV: ${JSON.stringify(csvR)}
UI: ${JSON.stringify(uiR)}
TU TAREA: integrar el parser y el CSV en la interfaz (lee primero el código real de los tres; si algo no coincide con el contrato, adáptate al código real o corrige el desajuste mínimo).
1. ProjectPage: al seleccionar un archivo en el explorador:
   - .txt/.mod/.gfx/.gui/.sfx/.asset -> parse_file en un hilo (QThreadPool/QRunnable o similar, sin bloquear la UI con archivos grandes) y mostrar en la vista previa un QTabWidget con: "Estructura" (QTreeWidget clave / operador / valor / línea, expandible, con búsqueda), "Código fuente" (QPlainTextEdit de solo lectura con números de línea, resaltado sencillo de sintaxis Clausewitz con colores acordes al tema, y resaltado de líneas con error), "Diagnósticos" (lista con icono de severidad y mensaje en el idioma actual vía Diagnostic.message(lang); doble clic salta a la línea en el código y al nodo en la estructura) y "JSON" (to_json con indentación). Los mensajes se re-traducen al cambiar de idioma.
   - .csv -> abrir en LocalisationPage y cambiar a esa página.
   - imágenes .tga/.png/.bmp/.dds/.jpg -> vista previa de la imagen con Pillow (convertir a QImage; si Pillow no puede abrir un .dds, mensaje amable).
   - Si en la carpeta del mod hay un archivo .mod hermano (p.ej. VSM.mod junto a VSM/) o dentro, muéstralo parseado en el grupo de rutas (name/path/user_dir).
   - Botón "Validar mod": recorre en segundo plano todos los archivos Clausewitz y CSV del mod con barra de progreso y muestra una tabla de diagnósticos (archivo, línea, severidad, mensaje); doble clic abre el archivo en la vista previa en esa línea. Con el corpus del usuario debe encontrar las llaves sin cerrar de somaliland_shago.txt y zulu_expancionshago.txt.
2. LocalisationPage: "Abrir CSV…" y apertura desde ProjectPage: QAbstractTableModel sobre LocalisationFile (SOLO LECTURA en esta iteración: dilo en la UI con un aviso discreto) con columnas Clave, English, Español(Spanish), Français, Deutsch y opción de mostrar todas las columnas; las filas de comentario/vacías ocultas por defecto con un conmutador; buscador con QSortFilterProxyModel sobre clave y textos; contador de filas; panel de diagnósticos de lint (mensajes en el idioma actual); debe cargar text.csv de 3,6 MB de forma fluida (< 3 s, sin congelar la UI; mide).
3. Añade las claves i18n nuevas en es.json y en.json (paridad), extiende tools/screenshot.py con --open-file (abrir un archivo concreto en la vista previa o en localización) y --validate (ejecutar Validar mod antes de capturar), y añade tests/test_ui_integration.py (offscreen): abrir un .txt del corpus y comprobar árbol/diagnósticos, abrir somaliland_shago.txt y comprobar el diagnóstico unclosed_block en línea 1, abrir text.csv y comprobar el número de filas del modelo, cambiar de idioma con un archivo abierto, validar el mod del usuario (${ZIPCORPUS}/VSM) y encontrar los 2 errores. Sin avisos Qt.
4. Genera capturas en ${SCRATCH}/screens/integrate/ (es y en) de: ProjectPage con "${ZIPCORPUS}/VSM" como mod y somaliland_shago.txt abierto en la pestaña Diagnósticos, ProjectPage tras Validar mod, ProjectPage con un archivo de historia de provincia en Estructura, LocalisationPage con "${TEMPLATE}/localisation/text.csv" y con 00_VSM_decisions.csv del usuario; míralas con Read e itera hasta que estén pulidas.
Ejecuta ${TEST_CMD} al final y reporta la salida real.`, { label: 'integrate:ui', phase: 'Integrate', schema: BUILD_SCHEMA })

// ---------------------------------------------------------------- VERIFY + FIX
const VERIFY_RULES = `
Eres un VERIFICADOR ADVERSARIAL independiente: tu trabajo es encontrar fallos reales, no confirmar que todo está bien. No modifiques archivos del proyecto (escribe tus scripts de prueba en ${SCRATCH}/verify/). Reproduce cada hallazgo ejecutándolo de verdad antes de reportarlo; no reportes especulaciones. Clasifica: critical (pérdida/corrupción de datos, crash, funcionalidad pedida ausente), major (comportamiento incorrecto visible, incumplimiento del contrato, bug de traducción visible, problema serio de diseño/usabilidad), minor (detalles). Si un hallazgo previo ya está corregido, no lo repitas.`

const COMPONENTS = [
  {
    key: 'parser',
    effort: 'max',
    verify: (prev) => `${COMMON}
${PARSER_CONTRACT}
${VERIFY_RULES}
Componente: vic2studio.core.clausewitz (${P}/src/vic2studio/core/clausewitz y tests/test_clausewitz_*.py). Lee todo el código.
Intenta romperlo: (1) ida y vuelta byte a byte sobre TODO el corpus (ambas rutas) con tu propio script, no solo con sus pruebas; (2) casos límite que el autor pudo olvidar: cadenas multilínea, comillas dentro de palabras (a"b), operadores pegados (a>=b, a=<b, ===), # dentro de comillas, \\r sueltos, tabs/espacios Unicode (U+00A0), caracteres de control, archivo de 0 bytes, solo "}", 10.000 niveles de anidación (¿RecursionError?), archivos enormes (genera 20 MB y mide), tokens rarísimos; (3) API de edición: secuencias de set/append/insert/remove encadenadas en bloques de una línea, vacíos, al final de archivo sin salto de línea final, con comentarios al final de línea ("a = b # c" y luego set a), en CRLF; tras cada edición re-parsear debe dar 0 errores y el árbol esperado, y el texto no editado debe quedar idéntico; valores con espacios/comillas/caracteres especiales en set (¿se generan comillas?, ¿qué pasa con un valor que contiene comillas?); (4) JSON: invariante del contrato, from_json con entradas inválidas (¿error claro?), include_comments; simplify; (5) diagnósticos: posiciones exactas, mensajes es/en para todos los códigos, los 2 archivos rotos del usuario señalan political_decisions en la línea 1; CLI check/tojson y su código de salida; (6) fuzzing propio con otra semilla y mutaciones distintas; (7) cumplimiento EXACTO del contrato (nombres, firmas, tipos de retorno); (8) compatibilidad Python 3.10 (ast.parse con feature_version=(3,10) sobre cada archivo); (9) rendimiento corpus; (10) calidad del código: claridad, duplicación, comentarios.
${prev}`,
    fix: 'vic2studio.core.clausewitz (src/vic2studio/core/clausewitz/ y tests/test_clausewitz_*.py)',
  },
  {
    key: 'csv',
    verify: (prev) => `${COMMON}
${CSV_CONTRACT}
${VERIFY_RULES}
Componente: vic2studio.core.csvloc (${P}/src/vic2studio/core/csvloc y tests/test_csvloc_*.py). Lee todo el código.
Intenta romperlo: ida y vuelta byte a byte de todos los .csv (y .csv.bak) de ambos corpus con tu propio script; casos límite (archivo vacío, solo "\\n", sin salto final, CR sueltos, BOM, líneas con 1, 14, 15 y 40 campos, comillas sin cerrar, "#" a mitad de línea, clave con espacios, campo con "x" que no es el marcador, mayúsculas "X"); edición (set en filas cortas, sin x, con extras tras x; add_row en archivo sin salto final; remove_row de duplicados; caracteres no cp1252 -> error claro antes de escribir); write_csv_file (atómico, .bak, codificación); to_json/from_json con entradas inválidas; LocalisationDB (orden, mod>vanilla, primera clave gana, source_of, overrides) contra la carpeta real de localisation de la plantilla + la del usuario; lint sobre los 3 CSV del usuario (debe detectar las filas sin x, la cabecera, y los campos entre comillas con ";"); mensajes es/en para todos los códigos; CLI; rendimiento (text.csv < 1,5 s); contrato exacto; compatibilidad Python 3.10 (ast feature_version); calidad del código.
${prev}`,
    fix: 'vic2studio.core.csvloc (src/vic2studio/core/csvloc/ y tests/test_csvloc_*.py)',
  },
  {
    key: 'ui',
    verify: (prev) => `${COMMON}
${UI_CONTRACT}
${VERIFY_RULES}
Componente: interfaz (src/vic2studio/app.py, __main__.py, i18n/, ui/, tools/screenshot.py, tests/test_ui_*.py, tests/test_i18n.py), incluida la integración con el parser y el CSV en ProjectPage y LocalisationPage. Lee todo el código.
Comprueba: (1) arranque real "cd ${P} && QT_QPA_PLATFORM=offscreen timeout 20 python3 -c ..." creando la app y la ventana sin excepciones ni avisos Qt (instala qInstallMessageHandler); también python3 -m vic2studio debe arrancar (ciérralo con un QTimer o timeout); (2) cambio de idioma: recorre TODOS los widgets visibles y ocultos de las 5 páginas (texto, tooltips, placeholders, títulos de columnas de tablas/árboles, títulos de pestañas, barra de estado, títulos de grupos) en es y en: cualquier texto que no cambie y no sea un nombre propio/ruta/dato es un fallo de traducción; también tras abrir un archivo y tras Validar mod; (3) paridad i18n y claves usadas inexistentes; textos en español con buena ortografía (tildes); (4) capturas: genera con tools/screenshot.py en ${SCRATCH}/screens/verify/ las 5 páginas en es y en, ProjectPage con mod "${ZIPCORPUS}/VSM" y somaliland_shago.txt abierto, tras Validar mod, y LocalisationPage con text.csv; MÍRALAS con Read y critica con ojo de diseñador: fidelidad a la estética Victoria II (bronce/dorado envejecido, pergamino, terciopelo rojo, madera, serif), legibilidad/contraste, alineaciones, recortes de texto (especialmente en inglés vs español, que es más largo), elementos superpuestos, espaciado, coherencia entre páginas; también a 1100x700 (mínimo) y 1920x1080; (5) funcionalidad: atajos Ctrl+1..5, persistencia QSettings (usa QSettings con una ruta temporal o setPath para no ensuciar la config del usuario... y comprueba si la app la contamina durante las pruebas), rutas inválidas, archivo binario o enorme en la vista previa, CSV de 3,6 MB sin congelar la UI (mide), Validar mod encuentra los 2 errores del usuario, doble clic en diagnóstico salta a la línea; (6) pruebas de UI existentes: ¿prueban de verdad o son triviales?; (7) compatibilidad Python 3.10 (ast feature_version); (8) calidad del código.
Incluye en screenshots las rutas de tus capturas.
${prev}`,
    fix: 'la interfaz (src/vic2studio/app.py, __main__.py, i18n/, ui/, assets/, tools/, tests/test_ui_*.py, tests/test_i18n.py)',
  },
  {
    key: 'docs',
    verify: (prev) => `${COMMON}
${VERIFY_RULES}
Componente: documentación y empaquetado (${P}/ARCHITECTURE.md, README.md, pyproject.toml, requirements.txt, packaging/). Lee también el código real del proyecto.
Comprueba: (1) el árbol de directorios de ARCHITECTURE.md coincide con los archivos reales (lo implementado existe; lo que no existe está marcado como planificado); (2) toda API, comando, ruta o afirmación técnica de los documentos coincide con el código real (nombres de funciones, CLI check/tojson, esquema JSON, códigos de diagnóstico, comportamiento de LocalisationDB, idiomas); (3) ejecuta literalmente los comandos del README (ejecutar la app offscreen con timeout, pruebas, CLI check sobre ${ZIPCORPUS}/VSM, tojson) y confirma que funcionan como se describe; (4) pyproject.toml válido (tomllib), entry point apunta a una función existente, package-data cubre los archivos de datos reales (json, qss, assets), y si es posible prueba la construcción con "python3 -m pip wheel . --no-deps --no-build-isolation -w ${SCRATCH}/wheel" (si falla por falta de red o de setuptools, dilo) y que el wheel contiene los json; (5) packaging/vic2studio.spec y scripts referencian rutas existentes; (6) calidad del español, claridad, honestidad de las afirmaciones (nada de afirmar funcionalidades no implementadas como hechas); (7) la justificación del stack y el diseño del mapa son técnicamente correctos.
${prev}`,
    fix: 'la documentación y el empaquetado (ARCHITECTURE.md, README.md, pyproject.toml, requirements.txt, packaging/)',
  },
]

const runVerify = (c, prevText, round) => agent(c.verify(prevText), {
  label: 'verify:' + c.key + ':r' + round, phase: 'Verify', schema: FINDINGS_SCHEMA, ...(c.effort ? { effort: c.effort } : {}),
})

const runFix = (c, findings, round) => agent(`${COMMON}
${c.key === 'parser' ? PARSER_CONTRACT : c.key === 'csv' ? CSV_CONTRACT : c.key === 'ui' ? UI_CONTRACT : ''}
TU TAREA: corregir los hallazgos de un verificador adversarial sobre ${c.fix}.
Hallazgos (JSON):
${JSON.stringify(findings, null, 2)}
Para cada hallazgo: reprodúcelo primero; si es real, corrígelo de raíz y añade una prueba de regresión; si tras reproducirlo concluyes que no es un fallo (o que corregirlo contradice el contrato o los requisitos), no lo cambies y explica por qué en not_fixed. Corrige todos los critical y major, y los minor razonables. No cambies la API pública del contrato; si un cambio afecta a otros componentes (p.ej. la UI usa el parser), busca los usos con grep y mantén todo funcionando. Solo toca archivos de tu componente salvo un ajuste mínimo imprescindible en un llamador. ${c.key === 'ui' ? 'Tras corregir, regenera capturas en ' + SCRATCH + '/screens/fix' + round + '/ y míralas con Read para confirmar los arreglos visuales.' : ''}
Al final ejecuta ${TEST_CMD} y reporta la salida real (todas las pruebas deben pasar).`, {
  label: 'fix:' + c.key + ':r' + round, phase: 'Fix', schema: FIX_SCHEMA, ...(c.effort ? { effort: c.effort } : {}),
})

const MAX_ROUNDS = 2
const results = await pipeline(COMPONENTS, async (c) => {
  const history = []
  let prevText = ''
  for (let round = 1; round <= MAX_ROUNDS; round++) {
    const v = await runVerify(c, prevText, round)
    if (!v) { history.push({ round, verify: null }); break }
    const actionable = v.findings.filter(f => f.severity !== 'minor' || round === 1)
    log(c.key + ' ronda ' + round + ': ' + v.findings.length + ' hallazgos (' + v.findings.filter(f => f.severity === 'critical').length + ' critical, ' + v.findings.filter(f => f.severity === 'major').length + ' major)')
    if (actionable.length === 0) { history.push({ round, verify: v, fix: null }); break }
    const fx = await runFix(c, actionable, round)
    history.push({ round, verify: v, fix: fx })
    prevText = 'HALLAZGOS DE LA RONDA ANTERIOR Y RESULTADO DE LA CORRECCIÓN (confirma que están realmente corregidos y busca fallos NUEVOS, incluidos los que hayan introducido las correcciones):\n' + JSON.stringify({ findings: v.findings, fix: fx }, null, 2)
  }
  return { component: c.key, history }
})

return { build: { parser: parserR, csv: csvR, ui: uiR, docs: docsR }, integration: integ, verification: results }

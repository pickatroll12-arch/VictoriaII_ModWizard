export const meta = {
  name: 'revision-adversarial-ui-ronda-final',
  description: 'Segunda revisión adversarial de la última ronda de la interfaz (commit 1ef8b73), con reproducción, mutación y verificación independiente',
  phases: [
    { title: 'Revisar', detail: 'un revisor por grupo de arreglos: reproducir antes/después, mutación y regresiones' },
    { title: 'Verificar', detail: 'un escéptico independiente por grupo intenta refutar cada hallazgo' },
  ],
}

const SCRATCH = '/tmp/claude-0/-home-user-VictoriaII-ModWizard/fc57859e-57cd-5f57-a8a9-c0c50763ef14/scratchpad/review'

const COMMON = `
Contexto: proyecto «Victoria II Mod Studio» (Python + PySide6), repositorio en /home/user/VictoriaII_ModWizard.
Lee primero CONTINUAR_EN_CLAUDE_CODE.md §5 paso 1 y §6 (límites que se dejaron a propósito: NF-DOC-DELETE,
NF-JSON-HELD-ROOT, NF-VALIDATE-TREE-RELEASE, basura congelada en cadena, etc. NO los reportes como hallazgos).

Qué se revisa: el commit 1ef8b73 («Interfaz: árbol grande liberado fuera del hilo de la interfaz, etiquetas UTF-16 y
repaso»). Estado anterior a la ronda: cfb65a5. Estado actual: 94bbe06 (HEAD de main). El commit del parser 4c62668 ya
fue verificado; solo entra si interactúa con lo tuyo. Mira el diff con: git -C /home/user/VictoriaII_ModWizard show 1ef8b73

REGLAS ESTRICTAS:
- NO modifiques el árbol de trabajo ni el estado git de /home/user/VictoriaII_ModWizard (nada de checkout, stash,
  commit, worktree add, ni editar archivos). Otro agente trabaja allí. Para experimentar haz tus propias copias:
    mkdir -p DIR/after DIR/before
    git -C /home/user/VictoriaII_ModWizard archive 94bbe06 | tar -x -C DIR/after
    git -C /home/user/VictoriaII_ModWizard archive cfb65a5 | tar -x -C DIR/before
  donde DIR es tu carpeta propia (te la doy abajo). Las mutaciones (deshacer un arreglo para ver si su prueba falla)
  se hacen en otra copia DIR/mut.
- Entorno: cd a la copia y usa  QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" PYTHONPATH=src
  python3 (Python 3.13 + PySide6 6.12). Hay Python 3.10.20 + PySide6 6.11.3 en /tmp/py310/bin/python.
  Pruebas: python3 -m unittest discover -s tests (unos 100 s), o módulos/pruebas concretas con -k o test_x.Clase.metodo.
- La máquina tiene 4 CPU compartidas con otro agente: las pruebas de latido (mayor hueco del hilo de la interfaz)
  pueden fallar por carga. Repítelas solas antes de darlas por rotas, y no reportes una medida de tiempo salvo que
  falle de forma consistente y con margen claro.
- No hay corpus del juego (VIC2_CORPUS) en esta máquina; usa la muestra tests/fixtures/shago_mod_min y archivos
  sintéticos que generes tú (UTF-16, archivos grandes, etc.). Nunca descargues datos de Paradox.
- Para la interfaz, puedes escribir scripts propios en DIR que construyan la MainWindow offscreen (mira tests/_qt.py,
  tests/test_ui_viewer.py y tools/screenshot.py) y capturas PNG que puedes mirar con la herramienta Read.
- Un hallazgo solo cuenta si lo REPRODUJISTE: da el comando exacto y la salida observada. Nada de «podría pasar».
  Si algo es solo una sospecha sin reproducción, ponlo en notes, no en findings.
- Busca también regresiones: API de Qt posterior a 6.5, sintaxis o biblioteca de Python posterior a 3.10, hilos o
  temporizadores que quedan vivos, textos visibles sin pasar por tr() o claves sin traducir, condiciones de carrera.
- Escribe los textos de tu informe en español.
`

const GROUPS = [
  {
    key: 'hilos-liberacion',
    title: 'Hilos, liberación del árbol y entrega de resultados',
    prompt: `Tu grupo: NF-TREE-RELEASE y TASKS-HANDOFF-RACE, más la lente «hilos y temporizadores vivos».
- NF-TREE-RELEASE: al cambiar de archivo, el análisis viejo se desmonta en segundo plano por trozos
  (ui/tasks.py: release_in_background, POOL_RELEASE, RELEASE_DELAY, RELEASE_CHUNK; ui/viewers/clausewitz_viewer.py:
  dismantle_load). Nada de Qt debe salir de su hilo (load.document = None antes de entregar). Comprueba: que ningún
  objeto Qt (QTextDocument, QObject) se destruye o se toca fuera del hilo de la interfaz; cambios de archivo muy
  rápidos (A→B→A→C en ráfaga); cerrar la ventana o salir de la app (app.main llama cancel_all/wait_for_tasks) con una
  liberación pendiente; que la memoria de verdad se libera; que la prueba de latido mide lo que dice.
- TASKS-HANDOFF-RACE: _Job ya no retiene lo entregado (entrega en una lista que vacía quien recibe). Comprueba: que
  no se pierde ni duplica un resultado, qué pasa si el receptor ya no existe, la interacción con gc.freeze y las
  referencias débiles que descongelan, y que la prueba intermitente del recolector (busca
  test_results_of_the_application_tasks_die_by_reference_counting y las de gc en tests/test_tasks.py) ya no falla:
  ejecútala muchas veces (p. ej. 30) en bucle.
- Lente: tras cerrar y destruir la MainWindow no debe quedar ningún QTimer activo ni hilo del QThreadPool trabajando;
  ninguna señal llega a un objeto destruido (busca «Internal C++ object already deleted» o RuntimeError en stderr).
Para cada arreglo: reprodúcelo contra cfb65a5 (el fallo existía), compruébalo en 94bbe06 (ya no), y haz una mutación
(revierte solo ese arreglo en una copia) para ver que alguna prueba falla; si ninguna falla, es un hallazgo
(«prueba que no detecta el fallo»).`,
  },
  {
    key: 'codificaciones-utf16',
    title: 'Codificaciones UTF-16, insignia «Ilegible» y ficha del archivo',
    prompt: `Tu grupo: NF-7, NF-UNREADABLE-BADGE, REVIEW-DIAG-TAB-UNREADABLE y NF-FACTS-PARTIAL.
- NF-7 y NF-UNREADABLE-BADGE: nombres de las 4 codificaciones UTF-16 (utf-16, utf-16-be-bom, utf-16-le, utf-16-be)
  en el visor (ENCODING_NAMES) y en la ficha del archivo (ENCODING_KEYS en ui/pages/project_page.py); insignia roja
  «Ilegible para el juego» en la cabecera del visor. Prueba con archivos UTF-16 LE/BE con y sin BOM, solo ASCII y con
  texto no ASCII, .txt y .csv y .mod, y comprueba en ES y EN que el nombre y la insignia salen bien.
- REVIEW-DIAG-TAB-UNREADABLE: la pestaña Diagnósticos ya no dice «Sin diagnósticos» en verde para un UTF-16.
- NF-FACTS-PARTIAL: la ficha ya no llama cp1252 a un UTF-8 de más de 2 MiB según dónde caiga el corte de lectura.
  Prueba con cortes justo en medio de un carácter multibyte (2, 3 y 4 bytes) en la frontera de 2 MiB, con BOM y sin él,
  y con un archivo que es cp1252 de verdad con bytes altos pasada la frontera.
- DECISIÓN que te pido además: el estado vacío «Ilegible para el juego» de la pestaña Diagnósticos
  (clave viewer.unreadable_text) ya no se ve nunca porque parse_file da unreadable_encoding (lee el párrafo de §5
  paso 1 del traspaso). Averigua si hay algún camino en el que todavía se pueda mostrar (p. ej. un .csv o un .mod en
  UTF-16, un error al leer, otro visor) y recomienda: quitarlo con sus claves, o dejarlo como red de seguridad.
  Pon tu recomendación razonada en el campo recommendation.
Para cada arreglo: reprodúcelo contra cfb65a5, compruébalo en 94bbe06 y haz una mutación para ver que alguna prueba
falla sin el arreglo; si ninguna falla, es un hallazgo.`,
  },
  {
    key: 'parpadeo-cancelacion',
    title: 'Reintentos sin parpadeo, cancelación de imágenes y singular',
    prompt: `Tu grupo: NF-R3-HEADER-BLINK, NF-IMAGE-BLINK, NF-IMAGE-CANCEL y NF-SINGULAR-LINE.
- NF-R3-HEADER-BLINK (visor de scripts) y NF-IMAGE-BLINK (ui/viewers/image_viewer.py): al reintentar un fallo de
  lectura, el fallo sigue a la vista hasta la respuesta o hasta LOADING_DELAY_MS (150 ms, ui/viewers/common.py), sin
  parpadear a «cargando…». Comprueba con respuestas rápidas (< 150 ms) y lentas (> 150 ms), reintentos repetidos,
  y cambiar a otro archivo durante el reintento (que el error viejo no se quede pegado al archivo nuevo).
- NF-IMAGE-CANCEL: cancelar la carga de una imagen ya no deja «cargando…». Prueba cancelar en cada momento (antes de
  arrancar la tarea, a mitad, justo al terminar) y con imágenes que fallan.
- NF-SINGULAR-LINE: «1 línea» en singular. Busca TODOS los sitios donde se muestran recuentos (líneas, archivos,
  errores, avisos, filas, diagnósticos...) en ES y EN y comprueba singular/plural con 0, 1 y 2; un plural roto en
  otro sitio del diff también cuenta.
Para cada arreglo: reprodúcelo contra cfb65a5, compruébalo en 94bbe06 y haz una mutación para ver que alguna prueba
falla sin el arreglo; si ninguna falla, es un hallazgo.`,
  },
  {
    key: 'textos-capturas',
    title: 'Textos cortados, navegación y traducciones',
    prompt: `Tu grupo: REVIEW-HEADER-ELIDE, REVIEW-FACTS-WRAP y REVIEW-NAV-NAMES, más la lente de traducciones.
- REVIEW-HEADER-ELIDE: la cabecera del visor recorta antes la ruta que la codificación (ElidedLabel en
  ui/viewers/common.py). REVIEW-FACTS-WRAP: la ficha del archivo hace salto de línea en los valores.
  REVIEW-NAV-NAMES: los nombres de módulo de la barra de navegación (ui/widgets/navigation.py) se parten en dos líneas
  si no caben, en vez de recortarse.
- Genera capturas con tools/screenshot.py (mira sus opciones con --help y en el README) en ES y EN, a 1100x700 y
  1920x1080, de la página Proyecto con un archivo abierto (por ejemplo
  --mod tests/fixtures/shago_mod_min/VSM --open-file decisions/zulu_expancionshago.txt y otras pestañas con --tab),
  la Localización y las demás páginas. Míralas TODAS con la herramienta Read y busca textos cortados, solapados,
  claves crudas sin traducir, columnas demasiado estrechas, «…» que esconden información importante. Prueba
  también nombres de archivo y rutas muy largas, y un archivo UTF-16 (nombre de codificación largo).
- Lente de traducciones: ejecuta tests/test_i18n.py y la pseudo-localización; revisa que cada clave nueva o cambiada
  en el diff (src/vic2studio/i18n/es.json y en.json) existe en los dos idiomas, que ningún texto visible del diff se
  salta tr(), y que el español es correcto.
Para cada arreglo: compáralo contra cfb65a5 (capturas antes/después si ayuda) y haz una mutación para ver que alguna
prueba falla sin el arreglo; si ninguna falla, es un hallazgo. Guarda en DIR las capturas que cites como prueba.`,
  },
  {
    key: 'compatibilidad',
    title: 'Compatibilidad con Qt 6.5 y Python 3.10',
    prompt: `Tu grupo: compatibilidad de TODO el código actual (94bbe06), con foco en lo que tocó 1ef8b73.
- Python 3.10: ejecuta la batería completa con /tmp/py310/bin/python (PySide6 6.11.3). Además comprueba la sintaxis
  de todo src/ y tests/ con ast.parse(src, feature_version=(3, 10)) y busca usos de biblioteca estándar posteriores
  a 3.10 (tomllib, ExceptionGroup, TestCase.enterContext, typing.Self, datetime.UTC, etc.).
- Qt 6.5: el mínimo declarado es PySide6 6.5. Crea un venv propio en DIR con Python 3.10 o 3.11
  (uv python find 3.10 da la ruta; uv está en /root/.local/bin/uv) e instala PySide6-Essentials==6.5.3 (o la 6.5.x
  que haya), numpy y Pillow, y ejecuta la batería completa. Si algo falla, averigua si es por una API de Qt posterior
  a 6.5 (busca la API en el diff y en el resto de src/vic2studio/ui) o por otra cosa. Revisa también a mano las
  llamadas Qt nuevas del diff contra la documentación de Qt 6.5 (enums con ámbito, firmas, métodos nuevos).
- Python 3.11 está en /usr/bin/python3.11: si tienes tiempo, pasa la batería también allí con PySide6<6.12.
Un hallazgo aquí es una prueba que falla o un fallo reproducido en una de esas combinaciones; da la salida exacta.`,
  },
]

const FINDINGS = {
  type: 'object',
  properties: {
    group: { type: 'string' },
    checked: {
      type: 'array',
      description: 'Un elemento por arreglo del grupo que revisaste',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          bug_reproduced_on_cfb65a5: { type: 'string', description: 'sí / no / no aplica, y cómo' },
          fixed_on_94bbe06: { type: 'string' },
          mutation_caught_by_tests: { type: 'string', description: 'qué mutación hiciste y qué prueba falló (o ninguna)' },
          notes: { type: 'string' },
        },
        required: ['id', 'bug_reproduced_on_cfb65a5', 'fixed_on_94bbe06', 'mutation_caught_by_tests'],
      },
    },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'identificador corto propio, p. ej. R2-UTF16-CSV-NAME' },
          title: { type: 'string' },
          severity: { type: 'string', enum: ['alta', 'media', 'baja'] },
          file: { type: 'string' },
          line: { type: 'integer' },
          description: { type: 'string' },
          repro: { type: 'string', description: 'comandos o script exactos para reproducirlo' },
          evidence: { type: 'string', description: 'salida observada' },
          suggested_fix: { type: 'string' },
          regression_test: { type: 'string', description: 'prueba que fallaría hoy y pasaría con el arreglo' },
        },
        required: ['id', 'title', 'severity', 'file', 'description', 'repro', 'evidence', 'suggested_fix'],
      },
    },
    recommendation: { type: 'string' },
    notes: { type: 'string', description: 'sospechas sin reproducir, cosas que no pudiste comprobar y por qué' },
  },
  required: ['group', 'checked', 'findings'],
}

const VERDICTS = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          finding_id: { type: 'string' },
          confirmed: { type: 'boolean' },
          severity: { type: 'string', enum: ['alta', 'media', 'baja'] },
          reproduction: { type: 'string', description: 'tu propia reproducción: comandos y salida' },
          reason: { type: 'string' },
          refined_fix: { type: 'string' },
        },
        required: ['finding_id', 'confirmed', 'reproduction', 'reason'],
      },
    },
  },
  required: ['verdicts'],
}

const results = await pipeline(
  GROUPS,
  g => agent(
    `${COMMON}\nTu carpeta propia: ${SCRATCH}/${g.key}\n\n${g.prompt}`,
    { label: `revisar:${g.key}`, phase: 'Revisar', schema: FINDINGS },
  ),
  async (review, g) => {
    if (!review) return null
    if (!review.findings || review.findings.length === 0) {
      return { group: g.key, title: g.title, review, verdicts: [] }
    }
    const v = await agent(
      `${COMMON}\nTu carpeta propia: ${SCRATCH}/${g.key}-verificar\n\n` +
      `Eres un verificador escéptico e independiente. Otro revisor reporta estos hallazgos sobre el grupo «${g.title}». ` +
      `Tu trabajo es intentar REFUTAR cada uno: reprodúcelo tú desde cero en tus propias copias (no te fíes de su ` +
      `evidencia), comprueba que no es un límite conocido de §6 del traspaso, que no es un efecto de la carga de la ` +
      `máquina, y que de verdad es un fallo del código y no de su script de prueba. Marca confirmed=true solo si lo ` +
      `reprodujiste tú. Si lo confirmas, ajusta la gravedad y propón el arreglo más pequeño y seguro.\n\n` +
      `Hallazgos:\n${JSON.stringify(review.findings, null, 2)}`,
      { label: `verificar:${g.key}`, phase: 'Verificar', schema: VERDICTS },
    )
    return { group: g.key, title: g.title, review, verdicts: v ? v.verdicts : null }
  },
)

return results.filter(Boolean)

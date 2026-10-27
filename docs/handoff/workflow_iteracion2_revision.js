export const meta = {
  name: 'iteracion-2-revision-adversarial',
  description: 'Verificación adversarial de la iteración 2 integrada: un revisor por componente y un verificador independiente que intenta refutar cada hallazgo',
  phases: [
    { title: 'Revisar', detail: 'un revisor por componente: invariantes I1–I12 y criterios de aceptación' },
    { title: 'Verificar', detail: 'un escéptico independiente por componente reproduce o refuta' },
  ],
}

const SCRATCH = '/tmp/claude-0/-home-user-VictoriaII-ModWizard/fc57859e-57cd-5f57-a8a9-c0c50763ef14/scratchpad/review-it2'
const VENVS = '/tmp/claude-0/-home-user-VictoriaII-ModWizard/fc57859e-57cd-5f57-a8a9-c0c50763ef14/scratchpad/review/compatibilidad-verificar'
const REV = args && args.rev ? args.rev : 'HEAD'

const COMMON = `
Proyecto «Victoria II Mod Studio» en /home/user/VictoriaII_ModWizard. Se revisa la iteración 2 integrada
(commit ${REV}); su diseño está en docs/diseno/wizard.md (§3 invariantes I1–I12, §4 reglas de escritura, §5 VFS,
§6 proyecto, §13 interfaz, §14.1 descriptor, §22 «Iteración 2» con sus 11 criterios de aceptación, §24 decisiones).
Lee también CONTINUAR_EN_CLAUDE_CODE.md §2 (convenciones).

YA ARREGLADO EN LA INTEGRACIÓN (no lo reportes otra vez salvo que el arreglo esté mal o incompleto):
cerrar o cambiar de mod con «Descartar» ya no deja autoguardado (Session.close_project(discard=)); el autoguardado
se borra si se deshace todo; las etiquetas undo.* del núcleo tienen texto; Project.open sin .mod apunta la VFS a
<juego>/mod/<Carpeta>.mod para poder crearlo; modfile._windows_rejects delega en vfs.paths.windows_name_problems;
la batería pasa con PySide6 6.5.0. tests/test_ui_real_project.py repite las pruebas de ventana contra el Project
real; tests/_fake_project.py imita al real para el resto.

REGLAS: no modifiques el repositorio ni su estado git. Trabaja en tu carpeta propia (abajo) con una copia:
  mkdir -p DIR/code && git -C /home/user/VictoriaII_ModWizard archive ${REV} | tar -x -C DIR/code
Entorno: QT_QPA_PLATFORM=offscreen VIC2STUDIO_SETTINGS_DIR="$(mktemp -d)" VIC2STUDIO_DATA_DIR="$(mktemp -d)"
VIC2STUDIO_CACHE_DIR="$(mktemp -d)" PYTHONPATH=src python3 (3.13 + PySide6 6.12). Otros: /tmp/py310/bin/python
(3.10 + 6.11.3) y ${VENVS}/v650min/bin/python (3.10 + PySide6 6.5.0, el mínimo). 4 CPU compartidas con otro
revisor: repite las pruebas de latido o de tiempos solas antes de darlas por rotas. Sin corpus del juego.
Un hallazgo solo cuenta si lo REPRODUJISTE (comando y salida) y, si es de código, con una prueba que falla sin el
arreglo. Busca también: API de Qt posterior a 6.5, Python posterior a 3.10, textos sin tr() o sin traducir, hilos
o temporizadores vivos, escrituras fuera de core/fileio.py. Informe en español.
`

const COMPONENTS = [
  { key: 'vfs-arquitectura', prompt: 'core/vfs (paths, rules, guard, vfs) y las reglas de arquitectura. I1: intenta escribir fuera del mod por todos los caminos (enlaces simbólicos a la carpeta del juego, «..», «\\\\», mayúsculas en Windows simuladas, mod dentro de <juego>/mod, descriptor de otro mod, carpeta hermana con prefijo común «TestMod2», el .mod por defecto cuando no hay descriptor). I7: resolución con WHOLE_FILE, UNION, KEYED (dos historias con el mismo id o TAG), replace_path recursivo y no, dependencias, mayúsculas distintas entre capas, DESCRIPTOR_REL. Rendimiento de scan con 10 000 archivos sintéticos. Arquitectura: tests/test_arch_writes.py (intenta colar una escritura cruda que no detecte: os.open con O_WRONLY, io.open, Path.touch, shutil.copyfileobj, open en modo "r+", Path.rename, os.makedirs…), core sin PySide6 (subproceso con PySide6 bloqueado importando todos los módulos de core), sintaxis 3.10 de src/ y tests/, y que ninguna prueba de la iteración 1 se haya debilitado (compara las aserciones de tests/ entre 7300a2f y la revisión).' },
  { key: 'diario', prompt: 'core/project/journal.py y recovery.py. I2: inyecta fallos con FAULT_HOOK en cada paso y con os._exit en un subproceso, con 1, 3 y 20 archivos, con CREATE, MODIFY, COPY_FROM_GAME y TRASH mezclados, y con el descriptor .mod (fuera de la carpeta del mod); PermissionError persistente; disco lleno simulado; recuperar dos veces; diario corrupto o a medias; .bak preexistente de otra sesión; originals/ que no se sobrescribe; autoguardado (write_recovery/clear_recovery, sesiones huérfanas de otro pid, de otro equipo y cerradas). Todo antes o todo después, nunca mezcla.' },
  { key: 'workspace-deshacer', prompt: 'core/project/workspace.py, undo.py, codecs.py, documents.py, project.py. I3/I4/I5/I12: guardar sin cambios no escribe ni crea .vic2studio/; abrir y leer no escribe; secuencias aleatorias de edición, deshacer, rehacer, revert, guardar y recargar con varias semillas (bytes exactos frente a un modelo de referencia); transacciones anidadas y que lanzan; dirty tras deshacer hasta el punto guardado; LRU que no expulsa sucios ni referenciados; documentos con errores de sintaxis (D17); cambios externos y accept_external/reload; uso desde otro hilo; cp1252 imposible y SourceMismatchError sin tocar el disco (I9); ajustes (project.json) que se deshacen; dos Project sobre el mismo mod (solo lectura).' },
  { key: 'descriptor-sesion', prompt: 'core/modfile.py (DescriptorSpec, render_descriptor, descriptor_problems, create_mod_skeleton, sanitize_folder, write_descriptor) y ui/session.py contra el Project real. Descriptor: prueba de oro con tests/fixtures/shago_mod_min/VSM.mod; Dark Age Mod / DAM; comentarios y claves desconocidas conservados; UTF-16 → cp1252; nombres reservados de Windows; carpeta ya existente; plantilla; create_mod_skeleton interrumpido a mitad (todo o nada); crear el .mod que falta y guardarlo. Session con Project.open real: abrir en segundo plano y cancelar o abrir otro a mitad (¿queda algún bloqueo o Project sin cerrar?), cerrar con y sin descartar, autoguardado cada N transacciones y por tiempo, restaurar y descartar sesiones huérfanas, cambios externos, conflicto al guardar, segunda ventana en solo lectura, señales emitidas una vez por operación.' },
  { key: 'interfaz', prompt: 'ui/main_window.py, ui/shell/**, ui/halls/**, ui/dialogs/**, i18n por fragmentos, tools/screenshot.py, contra el Project real. Recorre las 7 salas con Ctrl+1..7, Ctrl+S/Z/Y, contador de cambios, título con *, closeEvent con cambios; diálogos de revisión, conflicto, recuperación y nuevo mod; abrir un proyecto en segundo plano y cerrar la ventana a mitad; cambio de idioma con todo abierto y la pseudo-localización. Genera capturas ES y EN a 1100x700 y 1920x1080 de Inicio, Descriptor .mod, Archivos, Cambios pendientes y el diálogo de revisión con tools/screenshot.py --no-game-art (mira --help) y MÍRALAS TODAS con Read: textos cortados, solapados, claves crudas, columnas estrechas, botones que no caben. Repite al menos una con PySide6 6.5.0.' },
]

const FINDINGS = {
  type: 'object',
  properties: {
    component: { type: 'string' },
    checked: { type: 'string', description: 'qué comprobaste y cómo (también lo que salió bien)' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' }, title: { type: 'string' },
          severity: { type: 'string', enum: ['alta', 'media', 'baja'] },
          file: { type: 'string' }, line: { type: 'integer' },
          description: { type: 'string' }, repro: { type: 'string' }, evidence: { type: 'string' },
          suggested_fix: { type: 'string' }, regression_test: { type: 'string' },
        },
        required: ['id', 'title', 'severity', 'file', 'description', 'repro', 'evidence', 'suggested_fix'],
      },
    },
    notes: { type: 'string' },
  },
  required: ['component', 'checked', 'findings'],
}

const VERDICTS = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          finding_id: { type: 'string' }, confirmed: { type: 'boolean' },
          severity: { type: 'string', enum: ['alta', 'media', 'baja'] },
          reproduction: { type: 'string' }, reason: { type: 'string' }, refined_fix: { type: 'string' },
        },
        required: ['finding_id', 'confirmed', 'reproduction', 'reason'],
      },
    },
  },
  required: ['verdicts'],
}

const results = await pipeline(
  COMPONENTS,
  c => agent(`${COMMON}\nTu carpeta: ${SCRATCH}/${c.key}\n\nTu componente: ${c.prompt}`,
    { label: `revisar:${c.key}`, phase: 'Revisar', schema: FINDINGS }),
  async (review, c) => {
    if (!review || !review.findings || review.findings.length === 0) return { component: c.key, review, verdicts: [] }
    const v = await agent(`${COMMON}\nTu carpeta: ${SCRATCH}/${c.key}-verificar\n\nEres un verificador escéptico e ` +
      `independiente. Intenta REFUTAR cada hallazgo reproduciéndolo tú desde cero (no te fíes de su evidencia); ` +
      `descarta los que dependan de la carga de la máquina o de un error del script de prueba. confirmed=true solo si ` +
      `lo reprodujiste. Si lo confirmas, ajusta la gravedad y propón el arreglo más pequeño y seguro, con la prueba ` +
      `de regresión que falla sin él.\n\nHallazgos:\n${JSON.stringify(review.findings, null, 2)}`,
      { label: `verificar:${c.key}`, phase: 'Verificar', schema: VERDICTS })
    return { component: c.key, review, verdicts: v ? v.verdicts : null }
  },
)
return results.filter(Boolean)

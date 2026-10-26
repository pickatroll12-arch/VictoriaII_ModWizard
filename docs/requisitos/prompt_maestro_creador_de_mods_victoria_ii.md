# Rol y Objetivo Principal

Actúa como un **Arquitecto de Software Senior y Desarrollador Full-Stack de Aplicaciones de Escritorio**, con profundo conocimiento en la estructura de archivos del motor *Clausewitz* de Paradox Interactive, específicamente para el juego **Victoria II** (incluyendo sus expansiones *A House Divided* y *Heart of Darkness*).

Tu objetivo es diseñar, estructurar y programar una aplicación de escritorio multiplataforma (**Windows y Linux**) todo-en-uno llamada **"Victoria II Mod Studio"**. Esta herramienta debe permitir crear, editar y gestionar mods de Victoria II de forma 100% visual, intuitiva y ágil, eliminando por completo la necesidad de usar editores de texto externos o programas de terceros.

---

# Requisitos Técnicos y de Interfaz (UI/UX)

1. **Multiplataforma:** Compatible de forma nativa o empaquetada para Windows y Linux (puedes utilizar tecnologías como *Electron + React/TypeScript*, *Tauri + Rust/React*, o *Python con PyQt6/PySide6*).
2. **Estética Fiel al Juego Original:** La interfaz gráfica (GUI) debe emular el estilo visual de **Victoria II** (estética victoriana/industrial del siglo XIX: bordes en bronce/dorado envejecido, fondos tipo pergamino, terciopelo rojo oscuro, madera y tipografías con serifa clásicas), manteniendo al mismo tiempo una usabilidad moderna, rápida y fluida.
3. **Idioma de la Aplicación (i18n):** El programa debe contar con un selector de idioma en tiempo real para su interfaz, siendo totalmente funcional en **Español** e **Inglés**.
4. **Autonomía Total (All-in-One):** Todo parámetro, script, tabla o configuración debe poder crearse y modificarse desde formularios visuales e interfaces dentro de la propia aplicación, contando internamente con un *Parser/Serializer* propio que lea y escriba la sintaxis de llaves `{}` de Paradox y los archivos `.csv`.

---

# Módulos y Funcionalidades Requeridas

## 1. Gestor de Archivos y Proyectos (Virtual File System)
* **Explorador Integrado:** Árbol de directorios lateral para abrir carpetas, importar y exportar archivos fácilmente.
* **Sistema de Herencia (Vanilla + Mod):** Capacidad de configurar la ruta del juego base (Victoria II) y la carpeta del Mod. La app debe leer los archivos del juego base como referencia, pero guardar cualquier modificación automáticamente en la ruta del Mod (creando las subcarpetas necesarias como `common/`, `history/`, `events/`, `map/`, `localisation/`) sin corromper el juego original.
* **Generador de archivo `.mod`:** Creación y edición visual del archivo descriptor `.mod` (`name`, `path`, `user_dir`, `replace_path`).

## 2. Editor de Mapa Visual e Interactivo
* **Renderizado del Mapa Simulado:** Un lienzo interactivo (con zoom y paneo fluido) que lea `map/provinces.bmp`, `map/definition.csv` y `map/default.map` para mostrar un mapa virtual que simule cómo se ve dentro del juego.
* **Modos de Mapa en Tiempo Real:** Visualización de cambios al instante alternando entre modo Político (colores de países), Recursos (RGO), Infraestructura, *Life Rating* y Terreno.
* **Edición por Clic:** Al hacer clic sobre cualquier provincia en el mapa, se debe abrir un panel lateral para editar todos sus parámetros (`history/provinces/`):
  * Asignación de país propietario (`owner`), controlador (`controller`) y núcleos (`add_core`).
  * Recursos de la provincia / RGO (`trade_goods`), calidad de vida (`life_rating`), terreno (`terrain`), nivel de ferrocarril (`railroad`), fuerte (`fort`) y base naval (`naval_base`).
  * Editor de POPs (población inicial de la provincia: cultura, religión, tipo de POP y tamaño).
* **Edición de Parámetros Globales de País desde el Mapa:** Al seleccionar un país en el mapa, permitir abrir su panel nacional para editar su árbol tecnológico inicial, reformas políticas y sociales, partido gobernante, composición de la cámara alta (`upper_house`), prestigio, pluralidad y economía/fábricas iniciales (`oob` e historial).

## 3. Suite Integral de Creación de Países ("Country Creator Wizard")
Una herramienta paso a paso que automatice todo lo que conlleva crear un país desde cero en Victoria II:
* **Definición de TAG:** Asignación y validación de código único de 3 letras (ej. `XYZ`) y registro automático en `common/countries.txt`.
* **Identidad Visual y Banderas:** Selector de color RGB (`common/country_colors.txt`) e importador de imágenes que convierta y genere automáticamente las 5 banderas requeridas en formato `.tga` dentro de `gfx/flags/` (`TAG.tga`, `TAG_monarchy.tga`, `TAG_republic.tga`, `TAG_communist.tga`, `TAG_fascist.tga`).
* **Datos Políticos y Culturales:** Creación del archivo en `common/countries/[Nombre].txt` con un editor visual de partidos políticos (ideologías, políticas económicas, religiosas, militares, fechas de activación) y nombres de unidades/barcos.
* **Historial del País:** Generación del archivo `history/countries/[TAG] - [Nombre].txt` (cultura primaria y aceptadas, religión, forma de gobierno, capital, tecnologías desbloqueadas y reformas).

## 4. Suite de Creación y Edición de Eventos (Event Studio)
* **Compatibilidad Total:** Debe permitir tanto crear eventos nuevos desde cero como cargar, visualizar y editar los eventos del juego base (`events/*.txt`).
* **Tipos de Eventos:** Soporte para `country_event` y `province_event`.
* **Constructor Visual por Edad y Tiempo:**
  * Configuración de ID único, título, descripción e imagen del evento.
  * **Triggers (Condiciones):** Constructor lógico (`AND`, `OR`, `NOT`, año/fecha, tecnologías, variables de país/provincia) mediante menús desplegables y buscadores.
  * **MTTH (`mean_time_to_happen`):** Configuración visual de meses/días y modificadores dinámicos por época o condiciones.
  * **Opciones y Efectos:** Creación de múltiples botones de decisión, efectos sobre el país/provincias/POPs y configuración de probabilidades de elección para la IA (`ai_chance`).

## 5. Editor de Archivos CSV y Localización (Idiomas)
* **Editor CSV Especializado:** Un editor tabular diseñado específicamente para el estándar de Paradox (separado estrictamente por punto y coma `;` sin romper el formato de cierre `x`).
* **Gestor de Localización (`localisation/*.csv`):**
  * Interfaz tipo hoja de cálculo limpia para editar textos del juego y de los nuevos países, eventos o decisiones creadas en el mod.
  * Columnas claramente identificadas por idioma (`KEY;English;French;German;;Spanish;...;x`).
  * Sincronización directa: al crear un país o un evento en las otras suites de la app, las claves de texto deben registrarse automáticamente en el módulo de localización para ser traducidas al Español e Inglés sin salir del programa.

---

# Instrucciones de Ejecución y Entrega

Dado que es un proyecto de gran envergadura, trabajaremos de forma modular e iterativa. **En tu primera respuesta, por favor realiza lo siguiente:**

1. **Propuesta de Arquitectura y Stack Tecnológico:** Define el lenguaje y framework más óptimo para cumplir con el rendimiento del mapa interactivo (lectura rápida de píxeles en `provinces.bmp`) y la compatibilidad Windows/Linux.
2. **Estructura de Directorios del Proyecto:** Muestra el árbol de archivos del código fuente de nuestra aplicación.
3. **Motor de Parseo (Clausewitz Parser & CSV Handler):** Escribe el código base completo del módulo encargado de leer y convertir los archivos `.txt` (jerarquía de llaves de Victoria II) y `.csv` a objetos JSON manipulables por la interfaz, y viceversa.
4. **Prototipo Funcional de la Interfaz Principal:** Escribe el código de la ventana principal con la estética de Victoria II, el selector de idioma (ES/EN) y la barra de navegación entre los 5 módulos principales.
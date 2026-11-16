"""``python -m vic2studio`` y el ejecutable de PyInstaller.

El trabajador del taller de mapas arranca con ``multiprocessing`` en modo «spawn». En el ejecutable congelado, el
proceso hijo vuelve a lanzar este mismo ejecutable: ``freeze_support`` lo desvía al trabajador antes de cargar Qt,
en vez de abrir otra ventana. Sin congelar no hace nada.
"""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

    from vic2studio.app import main

    raise SystemExit(main())

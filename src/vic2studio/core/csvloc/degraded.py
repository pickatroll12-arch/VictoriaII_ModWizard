"""Filas de localización degradadas (H15): letras no ASCII perdidas como «?».

Una sola definición para la regla ``loc_copy_degraded`` (``core.validate``), su
explicador, el arreglo «Recuperar las filas de vanilla» y el filtro «degradadas» de
la sala Textos (``core.locsync``): así el aviso, el arreglo y la tabla cuentan lo
mismo (3 427 claves en el ``text.csv`` de VSM).

En el ``text.csv`` de VSM cada «?» sustituye a una letra acentuada y a 0–2
caracteres que la siguen (``Efficacité fiscale`` → ``Efficacit?fiscale``,
``Difficulté;Schwierigkeit`` → ``Difficult?Schwierigkeit``: el byte cp1252 leído
como el inicio de una secuencia UTF-8 se come lo que viene detrás).
"""

from __future__ import annotations

# Caracteres del juego que un «?» del mod puede sustituir además de la letra no ASCII.
DEGRADED_TAIL = 2


def is_degraded(mod_line: str, game_line: str) -> bool:
    """True si ``mod_line`` es ``game_line`` con letras no ASCII perdidas como ``?`` (y nada más cambia).

    Cada ``?`` del mod equivale a un ``?`` del juego o a un carácter no ASCII seguido de hasta ``DEGRADED_TAIL``
    caracteres cualesquiera; el resto del texto debe coincidir tal cual. Se recorre el texto del mod trozo a trozo
    (lo que hay entre dos ``?``) con el conjunto de posiciones del juego a las que se puede haber llegado: tiempo
    lineal en la longitud de las dos líneas por cada ``?``, sin expresiones regulares (compilar una por fila
    costaba 1,8 s en VSM y una racha de ``?`` daba retroceso exponencial).
    """
    if mod_line == game_line or "?" not in mod_line:
        return False
    parts = mod_line.split("?")
    if not game_line.startswith(parts[0]):
        return False
    size = len(game_line)
    reach = {len(parts[0])}
    for part in parts[1:]:
        following = set()
        for position in reach:
            if position >= size:
                continue
            char = game_line[position]
            if char == "?":
                last = position + 1
            elif char > "\x7f":
                last = min(position + 1 + DEGRADED_TAIL, size)
            else:
                continue
            for end in range(position + 1, last + 1):
                if game_line.startswith(part, end):
                    following.add(end + len(part))
        if not following:
            return False
        reach = following
    return size in reach

"""Problemas del taller (wizard §18.11): códigos, gravedades, arreglos y explicador.

Son problemas **del taller** (de un ``ForgeWorld``, de una importación o de una exportación por hacer), no de la
vista efectiva del mod: se enseñan en la revisión (pantalla 12) y en la importación, con su SimpleFix y su
explicador. Los textos son ``issue.<código>`` (el mensaje), ``explain.title.<código>`` y ``explain.outcome.<código>``
(el porqué, como el explicador del resto de problemas) y ``fix.mapforge.<arreglo>`` (la etiqueta del arreglo), en
``core/mapforge/texts``.

Una vez exportado, el mapa es un mapa normal del mod y lo valida la familia «map» (``check_map``, §16.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np

from ..clausewitz import Severity
from ..validate.model import Problem
from ..vfs.paths import VPath
from .params import ForgeParams, Owners

E, W, I = Severity.ERROR, Severity.WARNING, Severity.INFO

# código → (gravedad, arreglos; el primero es el seguro)
CODES: dict[str, tuple[Severity, tuple[str, ...]]] = {
    "replace_path_mod_files_remain": (E, ("trash_mod_files", "new_mod")),
    "forge_no_owned_provinces": (W, ("share_existing_tags",)),
    "forge_orientation_suspect": (W, ("flip_image",)),
    "forge_not_24bit": (E, ("convert_rgb",)),
    "forge_size": (W, ("pad_with_sea",)),
    "forge_color_reserved": (W, ("merge_reserved",)),
    "forge_tiny_province": (W, ("merge_tiny",)),
    "forge_seam_province": (I, ()),
    "province_isolated": (E, ("merge_isolated",)),
    "forge_land_sea_unknown": (E, ("choose_land_source",)),
    "forge_land_sea_ambiguous": (W, ("mark_land", "mark_sea")),
    "terrain_not_indexed": (E, ("convert_palette",)),
    "rivers_not_indexed": (E, ("convert_palette",)),
    "terrain_index_invalid": (W, ("align_terrain_mask",)),
    "terrain_index_placeholder": (W, ("use_common_index",)),
    "rivers_diagonal": (W, ("insert_corner",)),
    "rivers_in_water": (W, ("remove_river_water",)),
    "river_source_missing": (I, ()),
    "heightmap_size": (I, ()),
    "forge_too_many_provinces": (E, ("reduce_target",)),
    "forge_edit_conflict": (W, ("discard_edit",)),
    "forge_env_changed": (I, ()),
    "forge_export_conflict": (W, ("overwrite_export",)),
    "forge_loc_shadowed": (W, ("remove_shadowed_keys",)),
    "fmg_version_unknown": (W, ()),
    "fmg_aspect": (I, ()),
}


@dataclass(frozen=True)
class ForgeIssue:
    """Un problema del taller con su arreglo aplicable (las claves de ``CODES``)."""

    code: str
    args: dict = field(default_factory=dict)
    rel: str | None = None
    count: int = 1

    @property
    def severity(self) -> Severity:
        return CODES[self.code][0]

    @property
    def fixes(self) -> tuple[str, ...]:
        return CODES[self.code][1]

    @property
    def needs_confirmation(self) -> bool:
        return self.code in ("replace_path_mod_files_remain", "forge_no_owned_provinces")

    def problem(self) -> Problem:
        return Problem(self.code, self.severity, VPath.of(self.rel) if self.rel else None,
                       args=MappingProxyType(dict(self.args)), fixes=tuple(f"mapforge.{f}" for f in self.fixes))

    def message(self, lang: str = "en") -> str:
        from ..texts import text

        return text(f"issue.{self.code}", lang, **self.args)

    def explanation(self, lang: str = "en") -> tuple[str, str]:
        """``(título, consecuencia)`` del explicador."""
        from ..texts import text

        return (text(f"explain.title.{self.code}", lang, **self.args),
                text(f"explain.outcome.{self.code}", lang, **self.args))

    def fix_labels(self, lang: str = "en") -> list[str]:
        from ..texts import text

        return [text(f"fix.mapforge.{f}", lang) for f in self.fixes]


def params_issues(params: ForgeParams) -> list[ForgeIssue]:
    return [ForgeIssue(code, args) for code, args in params.validate()]


def world_issues(world, inputs=None, *, conflicts=(), env_changed: bool = False) -> list[ForgeIssue]:
    """Lo que la revisión (pantalla 12) enseña antes de exportar."""
    out = params_issues(world.params)
    r = world.raster
    if r is not None and r.owner is not None:
        owned = int((r.owner[1:r.land_count + 1] >= 0).sum())
        if owned == 0:
            out.append(ForgeIssue("forge_no_owned_provinces", {"mode": world.params.owners.value}))
        n = r.count
        if n + 1 > 65535:
            out.append(ForgeIssue("forge_too_many_provinces", {"count": n, "limit": 65535}))
        deg = np.bincount(r.edges.ravel(), minlength=n + 1) if r.edges is not None and r.edges.size \
            else np.zeros(n + 1, np.int64)
        lonely = np.flatnonzero(deg[1:] == 0) + 1
        if lonely.size:
            out.append(ForgeIssue("province_isolated", {"count": int(lonely.size), "first": int(lonely[0])},
                                  "map/provinces.bmp", int(lonely.size)))
    for c in conflicts:
        out.append(ForgeIssue("forge_edit_conflict", {"edit": c.edit.kind, "step": c.edit.step,
                                                      "reason": c.reason, "uid": c.edit.uid}))
    if env_changed:
        out.append(ForgeIssue("forge_env_changed", {}))
    if inputs is not None:
        if inputs.mod_trash:
            folders = sorted({"/".join(rel.split("/")[:2]) for rel in inputs.mod_trash})
            out.append(ForgeIssue("replace_path_mod_files_remain",
                                  {"count": len(inputs.mod_trash), "folders": ", ".join(folders),
                                   "example": inputs.mod_trash[0]}, None, len(inputs.mod_trash)))
        for rel in getattr(inputs, "loc_shadowed", []) or []:
            out.append(ForgeIssue("forge_loc_shadowed", {"file": rel}, rel))
        for rel in getattr(inputs, "export_conflicts", []) or []:
            out.append(ForgeIssue("forge_export_conflict", {"file": rel}, rel))
    return out


def fix_params(params: ForgeParams, fix: str) -> ForgeParams | None:
    """Los arreglos que cambian parámetros (los demás los aplica la importación o la exportación)."""
    if fix == "share_existing_tags":
        return params.with_(owners=Owners.EXISTING_TAGS)
    if fix == "reduce_target":
        land, sea = params.land_target(), params.sea_target()
        k = 60000 / max(1, land + sea)
        return params.with_(land_provinces=int(land * k), sea_provinces=int(sea * k))
    return None

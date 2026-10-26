"""Creador de Países (iteración 4): asistente paso a paso planificado."""

from __future__ import annotations

from ...i18n import N_
from .planned import FeatureGroup, PlannedModulePage


class CountriesPage(PlannedModulePage):
    key = "countries"
    title_key = N_("nav.countries")
    subtitle_key = N_("page.countries.subtitle")
    icon_name = "countries"
    iteration = 4
    intro_key = N_("countries.intro")
    numbered = True
    groups = (
        FeatureGroup(N_("countries.step.tag"), (N_("countries.f.tag"), N_("countries.f.tag_register"))),
        FeatureGroup(N_("countries.step.identity"), (N_("countries.f.color"), N_("countries.f.flags"))),
        FeatureGroup(N_("countries.step.politics"), (N_("countries.f.parties"), N_("countries.f.units"))),
        FeatureGroup(N_("countries.step.history"), (N_("countries.f.history"), N_("countries.f.history_fields"))),
    )

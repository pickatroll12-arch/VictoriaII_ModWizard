"""Validación cruzada con línea base, arreglos de un clic y explicador de conflicto (wizard §11)."""

from .baseline import BaselineCache, compute_baseline
from .context import ValidationContext, build_context, game_only_snapshot
from .explain import explain
from .fixes import FIXES, apply_fix, fixes_for, plan_fix, register_fix
from .model import (
    ChangePlan,
    Explanation,
    ExplainStep,
    FixSpec,
    PlannedChange,
    Problem,
    ValidationReport,
)
from .registry import RULES, RuleSpec, discover_rules, make_problem, rule
from .validator import Validator

__all__ = [
    "FIXES", "RULES", "BaselineCache", "ChangePlan", "ExplainStep", "Explanation", "FixSpec", "PlannedChange",
    "Problem", "RuleSpec", "ValidationContext", "ValidationReport", "Validator", "apply_fix", "build_context",
    "compute_baseline", "discover_rules", "explain", "fixes_for", "game_only_snapshot", "make_problem", "plan_fix",
    "register_fix", "rule",
]

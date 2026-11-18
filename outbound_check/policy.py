"""Loading and merging policy files."""

from __future__ import annotations

import copy
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


def default_policy() -> dict[str, Any]:
    text = resources.files("outbound_check").joinpath("default_policy.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    """Load a policy file on top of the defaults, so users only write what they change."""
    policy = default_policy()
    if path:
        user = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        policy = deep_merge(policy, user)
    return policy


def rule_params(policy: dict[str, Any], rule: str) -> dict[str, Any]:
    return dict((policy.get("rules") or {}).get(rule) or {})

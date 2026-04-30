"""Profile, ProfileSet dataclasses + YAML I/O."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ProfileValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    theme: str | None
    skinparams: dict[str, Any]
    handwritten: bool


@dataclass(frozen=True)
class SamplingEntry:
    profile: str
    probability: float


@dataclass(frozen=True)
class ProfileSet:
    profiles: tuple[Profile, ...]
    sampling: tuple[SamplingEntry, ...]

    def by_name(self, name: str) -> Profile:
        for p in self.profiles:
            if p.name == name:
                return p
        raise KeyError(name)


def load_profile_set(path: str | Path) -> ProfileSet:
    source = str(path)
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return _build_profile_set(raw, source)


def _build_profile_set(raw: Any, source: str) -> ProfileSet:
    if not isinstance(raw, dict):
        raise ProfileValidationError(f"{source}: top-level must be a mapping")
    missing = [k for k in ("profiles", "sampling") if k not in raw]
    if missing:
        raise ProfileValidationError(
            f"{source}: missing required top-level key(s): {', '.join(missing)}"
        )
    if not isinstance(raw["profiles"], list) or not raw["profiles"]:
        raise ProfileValidationError(f"{source}: 'profiles' must be a non-empty list")
    if not isinstance(raw["sampling"], list) or not raw["sampling"]:
        raise ProfileValidationError(f"{source}: 'sampling' must be a non-empty list")

    profiles = tuple(_build_profile(item, source, i) for i, item in enumerate(raw["profiles"]))

    names = [p.name for p in profiles]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ProfileValidationError(
            f"{source}: duplicate profile name(s): {', '.join(duplicates)}"
        )

    sampling = tuple(
        _build_sampling_entry(item, source, i) for i, item in enumerate(raw["sampling"])
    )

    name_set = set(names)
    for entry in sampling:
        if entry.profile not in name_set:
            raise ProfileValidationError(
                f"{source}: sampling references undefined profile '{entry.profile}'"
            )

    sampling = _normalize_probabilities(sampling, source)
    return ProfileSet(profiles=profiles, sampling=sampling)


def _build_profile(item: Any, source: str, idx: int) -> Profile:
    if not isinstance(item, dict):
        raise ProfileValidationError(f"{source}: profile #{idx} must be a mapping")

    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise ProfileValidationError(f"{source}: profile #{idx} missing or empty 'name'")

    theme = item.get("theme")
    if theme is not None and (not isinstance(theme, str) or not theme):
        raise ProfileValidationError(
            f"{source}: profile '{name}': theme must be null or non-empty string"
        )

    skinparams = item.get("skinparams") or {}
    if not isinstance(skinparams, dict):
        raise ProfileValidationError(f"{source}: profile '{name}': skinparams must be a mapping")
    if any(not isinstance(k, str) for k in skinparams):
        raise ProfileValidationError(f"{source}: profile '{name}': skinparam keys must be strings")

    handwritten = item.get("handwritten", False)
    if not isinstance(handwritten, bool):
        raise ProfileValidationError(f"{source}: profile '{name}': handwritten must be boolean")

    return Profile(
        name=name,
        theme=theme,
        skinparams=dict(skinparams),
        handwritten=handwritten,
    )


def _build_sampling_entry(item: Any, source: str, idx: int) -> SamplingEntry:
    if not isinstance(item, dict):
        raise ProfileValidationError(f"{source}: sampling #{idx} must be a mapping")

    profile = item.get("profile")
    if not isinstance(profile, str) or not profile:
        raise ProfileValidationError(f"{source}: sampling #{idx} missing or empty 'profile'")

    probability = item.get("probability")
    if isinstance(probability, bool) or not isinstance(probability, int | float):
        raise ProfileValidationError(
            f"{source}: sampling for '{profile}': probability must be a number"
        )
    if probability < 0:
        raise ProfileValidationError(
            f"{source}: sampling for '{profile}': probability must be non-negative"
        )

    return SamplingEntry(profile=profile, probability=float(probability))


def _normalize_probabilities(
    sampling: tuple[SamplingEntry, ...], source: str
) -> tuple[SamplingEntry, ...]:
    total = sum(e.probability for e in sampling)
    if total <= 0:
        raise ProfileValidationError(
            f"{source}: sampling probabilities sum to {total}; must be > 0"
        )
    if abs(total - 1.0) > 1e-9:
        logger.warning("%s: sampling probabilities sum to %s; normalizing to 1.0", source, total)
        return tuple(
            SamplingEntry(profile=e.profile, probability=e.probability / total) for e in sampling
        )
    return sampling

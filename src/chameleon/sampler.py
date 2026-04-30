"""Probability-weighted profile assignment with seed control."""

from __future__ import annotations

import os
import random
from collections.abc import Iterable
from dataclasses import dataclass

from chameleon.profile import Profile, ProfileSet


@dataclass(frozen=True)
class Assignment:
    input_path: str
    profile: Profile


def generate_seed() -> int:
    return int.from_bytes(os.urandom(8), "big") & ((1 << 63) - 1)


def assign_profiles(
    input_paths: Iterable[str], profile_set: ProfileSet, seed: int
) -> list[Assignment]:
    sorted_paths = sorted(input_paths)
    rng = random.Random(seed)
    population = [profile_set.by_name(e.profile) for e in profile_set.sampling]
    weights = [e.probability for e in profile_set.sampling]
    return [
        Assignment(input_path=path, profile=rng.choices(population, weights=weights, k=1)[0])
        for path in sorted_paths
    ]

from collections import Counter

import pytest

from chameleon.profile import Profile, ProfileSet, SamplingEntry
from chameleon.sampler import Assignment, assign_profiles, generate_seed


def _profile(name: str) -> Profile:
    return Profile(name=name, theme=None, skinparams={}, handwritten=False)


def _profile_set(weights: dict[str, float]) -> ProfileSet:
    profiles = tuple(_profile(n) for n in weights)
    sampling = tuple(SamplingEntry(profile=n, probability=p) for n, p in weights.items())
    return ProfileSet(profiles=profiles, sampling=sampling)


def test_same_seed_same_inputs_same_assignment() -> None:
    ps = _profile_set({"a": 0.5, "b": 0.5})
    paths = [f"f{i}.puml" for i in range(50)]
    a1 = assign_profiles(paths, ps, seed=42)
    a2 = assign_profiles(paths, ps, seed=42)
    assert a1 == a2


def test_different_seed_different_assignment() -> None:
    ps = _profile_set({"a": 0.5, "b": 0.5})
    paths = [f"f{i}.puml" for i in range(50)]
    a1 = [a.profile.name for a in assign_profiles(paths, ps, seed=1)]
    a2 = [a.profile.name for a in assign_profiles(paths, ps, seed=2)]
    assert a1 != a2


def test_input_iteration_order_does_not_affect_assignment() -> None:
    ps = _profile_set({"a": 0.5, "b": 0.5})
    paths = [f"f{i}.puml" for i in range(20)]
    forward = assign_profiles(paths, ps, seed=7)
    reversed_ = assign_profiles(reversed(paths), ps, seed=7)
    assert forward == reversed_


def test_returns_one_assignment_per_input() -> None:
    ps = _profile_set({"a": 1.0})
    paths = [f"f{i}.puml" for i in range(13)]
    assignments = assign_profiles(paths, ps, seed=0)
    assert len(assignments) == 13
    assert {a.input_path for a in assignments} == set(paths)
    assert all(a.profile.name == "a" for a in assignments)


def test_zero_weight_profile_never_sampled() -> None:
    ps = _profile_set({"a": 1.0, "b": 0.0})
    paths = [f"f{i}.puml" for i in range(200)]
    assigned = [a.profile.name for a in assign_profiles(paths, ps, seed=99)]
    assert "b" not in assigned


def test_distribution_roughly_matches_weights() -> None:
    ps = _profile_set({"a": 0.7, "b": 0.3})
    paths = [f"f{i}.puml" for i in range(2000)]
    counts = Counter(a.profile.name for a in assign_profiles(paths, ps, seed=12345))
    assert counts["a"] / 2000 == pytest.approx(0.7, abs=0.05)
    assert counts["b"] / 2000 == pytest.approx(0.3, abs=0.05)


def test_empty_input_yields_empty_assignment() -> None:
    ps = _profile_set({"a": 1.0})
    assert assign_profiles([], ps, seed=0) == []


def test_assignment_dataclass_carries_profile_object() -> None:
    ps = _profile_set({"a": 1.0})
    [assignment] = assign_profiles(["x.puml"], ps, seed=0)
    assert isinstance(assignment, Assignment)
    assert assignment.profile is ps.by_name("a")


def test_generate_seed_returns_nonneg_int_and_varies() -> None:
    seeds = {generate_seed() for _ in range(20)}
    assert all(isinstance(s, int) and s >= 0 for s in seeds)
    assert len(seeds) > 1

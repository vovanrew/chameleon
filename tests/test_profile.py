import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from chameleon.profile import ProfileValidationError, load_profile_set


def _write_yaml(tmp_path: Path, payload: Any) -> Path:
    p = tmp_path / "profiles.yaml"
    p.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return p


VALID: dict[str, Any] = {
    "profiles": [
        {
            "name": "default",
            "theme": None,
            "skinparams": {},
            "handwritten": False,
        },
        {
            "name": "whiteboard",
            "theme": "sketchy",
            "skinparams": {"shadowing": False},
            "handwritten": True,
        },
        {
            "name": "corporate",
            "theme": "cerulean",
            "skinparams": {"shadowing": True},
            "handwritten": False,
        },
    ],
    "sampling": [
        {"profile": "default", "probability": 0.5},
        {"profile": "whiteboard", "probability": 0.2},
        {"profile": "corporate", "probability": 0.3},
    ],
}


def _one_profile_payload(**overrides: Any) -> dict[str, Any]:
    profile = {
        "name": "a",
        "theme": None,
        "skinparams": {},
        "handwritten": False,
    }
    profile.update(overrides)
    return {
        "profiles": [profile],
        "sampling": [{"profile": "a", "probability": 1.0}],
    }


def test_load_valid(tmp_path: Path) -> None:
    ps = load_profile_set(_write_yaml(tmp_path, VALID))
    assert [p.name for p in ps.profiles] == ["default", "whiteboard", "corporate"]
    assert sum(s.probability for s in ps.sampling) == pytest.approx(1.0)
    wb = ps.by_name("whiteboard")
    assert wb.theme == "sketchy"
    assert wb.handwritten is True
    assert wb.skinparams == {"shadowing": False}


def test_by_name_missing(tmp_path: Path) -> None:
    ps = load_profile_set(_write_yaml(tmp_path, VALID))
    with pytest.raises(KeyError):
        ps.by_name("nope")


def test_duplicate_profile_names(tmp_path: Path) -> None:
    payload = dict(VALID)
    payload["profiles"] = [
        *VALID["profiles"],
        {
            "name": "default",
            "theme": None,
            "skinparams": {},
            "handwritten": False,
        },
    ]
    with pytest.raises(ProfileValidationError, match="duplicate"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_sampling_references_unknown_profile(tmp_path: Path) -> None:
    payload = dict(VALID)
    payload["sampling"] = [{"profile": "ghost", "probability": 1.0}]
    with pytest.raises(ProfileValidationError, match="undefined profile 'ghost'"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_probabilities_normalized_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    payload: dict[str, Any] = {
        "profiles": [
            {
                "name": "a",
                "theme": None,
                "skinparams": {},
                "handwritten": False,
            },
            {
                "name": "b",
                "theme": None,
                "skinparams": {},
                "handwritten": False,
            },
        ],
        "sampling": [
            {"profile": "a", "probability": 2.0},
            {"profile": "b", "probability": 2.0},
        ],
    }
    with caplog.at_level(logging.WARNING, logger="chameleon.profile"):
        ps = load_profile_set(_write_yaml(tmp_path, payload))
    assert sum(s.probability for s in ps.sampling) == pytest.approx(1.0)
    assert all(s.probability == pytest.approx(0.5) for s in ps.sampling)
    assert any("normalizing" in rec.message for rec in caplog.records)


def test_negative_probability(tmp_path: Path) -> None:
    payload = _one_profile_payload()
    payload["sampling"] = [{"profile": "a", "probability": -0.1}]
    with pytest.raises(ProfileValidationError, match="non-negative"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_zero_total_probability(tmp_path: Path) -> None:
    payload = _one_profile_payload()
    payload["sampling"] = [{"profile": "a", "probability": 0.0}]
    with pytest.raises(ProfileValidationError, match="must be > 0"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_empty_theme_string(tmp_path: Path) -> None:
    payload = _one_profile_payload(theme="")
    with pytest.raises(ProfileValidationError, match="theme"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_handwritten_not_bool(tmp_path: Path) -> None:
    payload = _one_profile_payload(handwritten="yes")
    with pytest.raises(ProfileValidationError, match="handwritten"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_skinparams_not_mapping(tmp_path: Path) -> None:
    payload = _one_profile_payload(skinparams=["shadowing"])
    with pytest.raises(ProfileValidationError, match="skinparams must be a mapping"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_missing_name(tmp_path: Path) -> None:
    payload: dict[str, Any] = {
        "profiles": [{"theme": None, "skinparams": {}, "handwritten": False}],
        "sampling": [{"profile": "a", "probability": 1.0}],
    }
    with pytest.raises(ProfileValidationError, match="name"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_missing_top_level_keys(tmp_path: Path) -> None:
    payload = {"profiles": []}
    with pytest.raises(ProfileValidationError, match="missing required"):
        load_profile_set(_write_yaml(tmp_path, payload))


def test_top_level_not_mapping(tmp_path: Path) -> None:
    p = tmp_path / "profiles.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ProfileValidationError, match="must be a mapping"):
        load_profile_set(p)


def test_empty_profiles_list(tmp_path: Path) -> None:
    payload = {"profiles": [], "sampling": [{"profile": "a", "probability": 1.0}]}
    with pytest.raises(ProfileValidationError, match="non-empty list"):
        load_profile_set(_write_yaml(tmp_path, payload))

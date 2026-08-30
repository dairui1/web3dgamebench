from pathlib import Path

from aetherplay.config import load_profiles, validate_matrix

ROOT = Path(__file__).resolve().parents[1]


def test_pilot_matrix_has_requested_six_profiles() -> None:
    season, profiles = validate_matrix(ROOT, "pilot-2026-09")
    assert len(season.profiles) == 6
    assert profiles["codex-sol-medium"].effort == "medium"
    assert profiles["codex-terra-high"].effort == "high"
    assert profiles["codex-luna-max"].effort == "max"
    assert profiles["claude-sonnet-default"].effort is None
    assert profiles["claude-opus-default"].effort is None
    assert profiles["pi-deepseek-v4-flash"].provider == "opencode-go"


def test_all_profiles_have_unique_ids() -> None:
    profiles = load_profiles(ROOT)
    assert len(profiles) == len(set(profiles))

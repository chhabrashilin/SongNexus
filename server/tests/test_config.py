import pytest

from songnexus.config import ConfigError, Settings, validate_for_serving

GOOD: dict[str, object] = {
    "environment": "staging",
    "allowed_origins": ["https://songnexus.web.app"],
    "firebase_project_id": "songnexus",
}


def test_development_is_exempt() -> None:
    validate_for_serving(Settings(environment="development"), {})


def test_a_complete_production_config_passes() -> None:
    validate_for_serving(Settings.model_validate(GOOD), {})


@pytest.mark.parametrize(
    ("override", "env", "message"),
    [
        ({"allowed_origins": ["http://localhost:5173"]}, {}, "ALLOWED_ORIGINS"),
        ({"allowed_origins": []}, {}, "ALLOWED_ORIGINS"),
        ({"firebase_project_id": ""}, {}, "FIREBASE_PROJECT_ID"),
        ({}, {"FIREBASE_AUTH_EMULATOR_HOST": "127.0.0.1:9099"}, "EMULATOR"),
    ],
)
def test_unsafe_production_configs_are_refused(
    override: dict[str, object], env: dict[str, str], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        validate_for_serving(Settings.model_validate({**GOOD, **override}), env)

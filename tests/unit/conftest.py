import os

# Force all feature flags on before any production code is imported.
# Module-level controller instantiations (e.g. `scorecard_controller = ScorecardController()`)
# call _check_enabled() at import time and will raise RuntimeError when features are off.
# Setting env vars here runs before test-file collection triggers those imports.
_FEATURE_ENV_VARS = {
    "ENABLE_SCORECARD_CONTROLLER": "true",
    "ENABLE_SLO_CONTROLLER": "true",
}
for _key, _val in _FEATURE_ENV_VARS.items():
    os.environ[_key] = _val

import pytest  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _ensure_settings_features_enabled():
    """Belt-and-suspenders: patch the settings singleton for tests where it was
    already imported before conftest.py env vars could take effect."""
    from src.settings import settings

    _prev = {
        "enable_scorecard_controller": settings.enable_scorecard_controller,
        "enable_slo_controller": settings.enable_slo_controller,
    }
    for attr in _prev:
        object.__setattr__(settings, attr, True)
    yield
    for attr, val in _prev.items():
        object.__setattr__(settings, attr, val)

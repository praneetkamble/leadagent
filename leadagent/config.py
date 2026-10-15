import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("LEADAGENT_DATA", ROOT / "data"))
PROFILE = Path(os.getenv("LEADAGENT_PROFILE", ROOT / "profile.json"))
FIXTURES = ROOT / "fixtures"
# Optional LLM (OpenAI-compatible). Unset => deterministic templates.
LLM_BASE_URL = os.getenv("LEADAGENT_LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LEADAGENT_LLM_API_KEY", "")
LLM_MODEL = os.getenv("LEADAGENT_LLM_MODEL", "")
# Live URL fetching is OFF by default. Fixtures are the supported input.
ALLOW_FETCH = os.getenv("LEADAGENT_ALLOW_FETCH", "") == "1"
CURRENT_YEAR = int(os.getenv("LEADAGENT_YEAR", "2026"))
MIN_FIT_TO_DRAFT = int(os.getenv("LEADAGENT_MIN_FIT", "40"))

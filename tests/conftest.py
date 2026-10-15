import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from leadagent.pipeline import RunStore


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path)

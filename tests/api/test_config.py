import pytest
from pydantic import ValidationError

from cad_api.config import Settings


def test_planning_llm_defaults():
    s = Settings(_env_file=None)
    assert s.llm_model == "deepseek-ai/DeepSeek-V4-Pro"
    assert s.llm_backend == "transformers"
    assert s.llm_trust_remote_code is False  # never run repo code unless explicitly enabled


def test_llm_backend_is_restricted():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_backend="openai")

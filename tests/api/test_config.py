import pytest
from pydantic import ValidationError

from cad_api.config import Settings


def test_no_llm_by_default():
    s = Settings(_env_file=None)
    assert s.llm_backend == "none"  # drawing generation is deterministic
    assert s.llm_trust_remote_code is False  # never run repo code unless explicitly enabled


def test_llm_backend_is_restricted():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_backend="openai")

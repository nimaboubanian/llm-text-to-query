import os
from dataclasses import asdict, dataclass

_ENV_VARS = {
    "retry": "FEATURE_RETRY",
    "chain_of_thought": "FEATURE_CHAIN_OF_THOUGHT",
    "self_correction": "FEATURE_SELF_CORRECTION",
}

_TRUTHY = {"1", "true", "yes", "on"}


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class GenerationFlags:
    """Feature-flag toggles for prompt-improvement techniques.

    These are architectural placeholders only — no behavior is implemented
    yet. They exist so retry loops, chain-of-thought prompting, and
    self-correction can be added later without threading new parameters
    through the pipeline. Every flag is part of the generation fingerprint
    and the session manifest: flipping one must invalidate cached results
    and be visible in provenance.
    """

    retry: bool = False
    chain_of_thought: bool = False
    self_correction: bool = False

    @classmethod
    def from_env(cls) -> "GenerationFlags":
        return cls(**{field: _env_bool(var) for field, var in _ENV_VARS.items()})

    def to_dict(self) -> dict:
        return asdict(self)

"""Cache-invalidation fingerprints for generation/execution artifacts."""
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

MANIFEST_FILENAME = "manifest.json"


@dataclass
class GenerationFingerprint:
    """Everything that determines a generated-SQL output, hashed to detect stale caches."""
    model: str
    prompt_template: str
    schema: str
    temperature: float
    max_tokens: int
    seed: int | None

    @property
    def hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def write_manifest(directory: Path, fingerprint_hash: str, details: dict) -> None:
    """Write a manifest recording the fingerprint hash and its human-readable inputs."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {"fingerprint": fingerprint_hash, **details}
    (directory / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2, default=str))


def read_manifest_fingerprint(directory: Path) -> str | None:
    """Read the fingerprint hash recorded in a directory's manifest, if any."""
    manifest_file = directory / MANIFEST_FILENAME
    if not manifest_file.exists():
        return None
    try:
        return json.loads(manifest_file.read_text()).get("fingerprint")
    except json.JSONDecodeError:
        return None


def collect_fingerprints(root: Path) -> dict[str, str]:
    """Collect fingerprint hashes from every manifest under a directory tree.

    Keys are the manifest's directory relative to root ("." for root itself,
    "seed_1", "model_slug/seed_2", etc. for nested generation layouts).
    """
    return {
        str(manifest_file.relative_to(root).parent): fingerprint_hash
        for manifest_file in sorted(root.rglob(MANIFEST_FILENAME))
        if (fingerprint_hash := read_manifest_fingerprint(manifest_file.parent)) is not None
    }

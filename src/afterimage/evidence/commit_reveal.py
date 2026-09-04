from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import BlindTwin, EvidenceManifest, EvidenceQuery, VersionStamp
from afterimage.storage import Repository


class CommitMismatch(RuntimeError):
    pass


def build_manifest(
    query: EvidenceQuery,
    twins: Sequence[BlindTwin],
    versions: VersionStamp,
    dataset_hash: str,
    excluded: Sequence[dict[str, str]] = (),
) -> EvidenceManifest:
    draft = EvidenceManifest(
        query=query,
        twins=tuple(twins),
        excluded=tuple(excluded),
        versions=versions,
        dataset_hash=dataset_hash,
        created_at=datetime.now(UTC),
    )
    commit_hash = canonical_sha256(draft.model_dump(mode="json", exclude={"commit_hash"}))
    return draft.model_copy(update={"commit_hash": commit_hash})


class CommitStore:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def persist(self, session_id: str, manifest: EvidenceManifest) -> str:
        expected = canonical_sha256(manifest.model_dump(mode="json", exclude={"commit_hash"}))
        if expected != manifest.commit_hash:
            raise CommitMismatch("manifest changed before persistence")
        artifact_hash = self.repository.save_artifact(
            session_id,
            "evidence_commit",
            manifest.model_dump(mode="json"),
            artifact_hash=manifest.commit_hash,
        )
        return artifact_hash

    def load(self, commit_hash: str) -> dict[str, Any] | None:
        return self.repository.get_artifact("evidence_commit", commit_hash)

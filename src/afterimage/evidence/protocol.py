from __future__ import annotations

from afterimage.contracts.models import (
    EvidenceDecision,
    EvidenceManifest,
    EvidenceQuery,
    VersionStamp,
)
from afterimage.storage import Repository

from .commit_reveal import CommitStore, build_manifest
from .metrics import EvidencePolicy, evaluate_evidence
from .retrieval import retrieve_twins
from .vault import OutcomeVault


class SealedTwinProtocol:
    def __init__(
        self, vault: OutcomeVault, repository: Repository, policy: EvidencePolicy | None = None
    ) -> None:
        self.vault = vault
        self.repository = repository
        self.commits = CommitStore(repository)
        self.policy = policy or EvidencePolicy()

    def commit(
        self,
        session_id: str,
        query: EvidenceQuery,
        versions: VersionStamp,
        dataset_hash: str,
    ) -> EvidenceManifest:
        twins = retrieve_twins(query, self.vault.blind_rows())
        manifest = build_manifest(query, twins, versions, dataset_hash)
        self.commits.persist(session_id, manifest)
        return manifest

    def reveal(self, session_id: str, manifest: EvidenceManifest) -> EvidenceDecision:
        persisted = self.repository.get_artifact("evidence_commit", manifest.commit_hash)
        if persisted is None:
            raise RuntimeError("evidence must be durably committed before reveal")
        outcomes = self.vault.reveal(twin.twin_id for twin in manifest.twins)
        reveal_hash = self.repository.save_artifact(
            session_id,
            "evidence_reveal",
            {
                "commit_hash": manifest.commit_hash,
                "outcomes": [o.model_dump(mode="json") for o in outcomes],
            },
        )
        return evaluate_evidence(
            manifest.twins, outcomes, manifest.commit_hash, reveal_hash, self.policy
        )

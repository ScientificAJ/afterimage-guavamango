from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import EvidenceMetrics, TournamentResult
from afterimage.storage import Repository

from .manifests import CandidateManifest, PromotionPolicy, TournamentSeal
from .promotion import build_entry, select_champion


class TournamentError(RuntimeError):
    pass


class TournamentRunner:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def preregister(
        self,
        session_id: str,
        candidates: Sequence[CandidateManifest],
        policy: PromotionPolicy,
        holdout_hash: str,
    ) -> TournamentSeal:
        candidate_hashes = tuple(canonical_sha256(candidate) for candidate in candidates)
        draft = {
            "tournament_id": str(uuid4()),
            "candidate_hashes": candidate_hashes,
            "promotion_policy_hash": canonical_sha256(policy),
            "holdout_hash": holdout_hash,
            "sealed_at": datetime.now(UTC),
        }
        seal = TournamentSeal(**draft, seal_hash=canonical_sha256(draft))
        self.repository.save_artifact(
            session_id,
            "tournament_seal",
            {
                "seal": seal.model_dump(mode="json"),
                "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
                "policy": policy.model_dump(mode="json"),
            },
        )
        return seal

    def reveal(
        self,
        session_id: str,
        seal: TournamentSeal,
        candidates: Sequence[CandidateManifest],
        policy: PromotionPolicy,
        results: Mapping[str, EvidenceMetrics],
    ) -> TournamentResult:
        if tuple(canonical_sha256(candidate) for candidate in candidates) != seal.candidate_hashes:
            raise TournamentError("candidate manifests changed after seal")
        if canonical_sha256(policy) != seal.promotion_policy_hash:
            raise TournamentError("promotion policy changed after seal")
        entries = []
        for manifest, manifest_hash in zip(candidates, seal.candidate_hashes, strict=True):
            metrics = results.get(manifest_hash)
            if metrics is None:
                raise TournamentError(f"missing sealed result for {manifest.identity.strategy_id}")
            entries.append(build_entry(manifest, manifest_hash, metrics, policy))
        champion = select_champion(entries)
        payload = {
            "seal_hash": seal.seal_hash,
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "champion": champion.identity.model_dump() if champion else None,
        }
        result = TournamentResult(
            tournament_hash=canonical_sha256(payload),
            entries=tuple(entries),
            champion=champion.identity if champion else None,
            champion_manifest_hash=champion.manifest_hash if champion else None,
            revealed_at=datetime.now(UTC),
        )
        self.repository.save_artifact(
            session_id, "tournament_result", result.model_dump(mode="json")
        )
        return result

from __future__ import annotations

import base64
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.exc import IntegrityError

from afterimage.contracts.hashing import canonical_json, canonical_sha256
from afterimage.contracts.models import ExecutionIntent, ExecutionWarrant, RiskDecision
from afterimage.storage import Database
from afterimage.storage.models import ConsumedNonceRow


class WarrantError(RuntimeError):
    pass


class WarrantAuthority:
    def __init__(self, key_path: str | Path, database: Database) -> None:
        self.key_path = Path(key_path)
        self.database = database
        self.private_key = self._load_or_create()

    def _load_or_create(self) -> Ed25519PrivateKey:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.key_path.parent, 0o700)
        if self.key_path.exists():
            if self.key_path.is_symlink():
                raise WarrantError("signing key path must not be a symbolic link")
            os.chmod(self.key_path, 0o600)
            return serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)  # type: ignore[return-value]
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        descriptor = os.open(
            self.key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
        return key

    def _public_b64(self) -> str:
        raw = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode()

    @staticmethod
    def _material(
        intent_hash: str,
        risk_vector_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        nonce: str,
    ) -> dict[str, object]:
        return {
            "intent_hash": intent_hash,
            "risk_vector_hash": risk_vector_hash,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "nonce": nonce,
        }

    def mint(
        self, intent: ExecutionIntent, decision: RiskDecision, ttl_seconds: int = 25
    ) -> ExecutionWarrant:
        if decision.status.value != "PASS" or decision.quantity != intent.quantity:
            raise WarrantError("risk decision does not authorize intent")
        if decision.decision_id != intent.risk_decision_id:
            raise WarrantError("risk decision id is not bound to intent")
        if decision.strategy_manifest_hash != intent.strategy_manifest_hash:
            raise WarrantError("strategy hash is not bound to risk decision")
        if decision.evidence_commit_hash != intent.evidence_commit_hash:
            raise WarrantError("evidence hash is not bound to risk decision")
        observed_quote_hash = canonical_sha256(intent.quote_material())
        if decision.quote_hash != observed_quote_hash:
            raise WarrantError("quote hash is not bound to risk decision")
        intent_hash = canonical_sha256(intent)
        risk_hash = canonical_sha256(decision)
        issued = datetime.now(UTC)
        expires = issued + timedelta(seconds=max(20, min(ttl_seconds, 30)))
        nonce = secrets.token_urlsafe(24)
        material = self._material(intent_hash, risk_hash, issued, expires, nonce)
        signature = base64.b64encode(self.private_key.sign(canonical_json(material))).decode()
        return ExecutionWarrant(
            intent=intent,
            intent_hash=intent_hash,
            risk_vector_hash=risk_hash,
            issued_at=issued,
            expires_at=expires,
            nonce=nonce,
            signature=signature,
            public_key=self._public_b64(),
        )

    def verify(self, warrant: ExecutionWarrant, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        if warrant.consumed_at is not None or now >= warrant.expires_at:
            return False
        if canonical_sha256(warrant.intent) != warrant.intent_hash:
            return False
        if warrant.public_key != self._public_b64():
            return False
        material = self._material(
            warrant.intent_hash,
            warrant.risk_vector_hash,
            warrant.issued_at,
            warrant.expires_at,
            warrant.nonce,
        )
        try:
            public = self.private_key.public_key()
            public.verify(base64.b64decode(warrant.signature), canonical_json(material))
        except (InvalidSignature, ValueError):
            return False
        return True

    def consume(self, warrant: ExecutionWarrant) -> ExecutionWarrant:
        now = datetime.now(UTC)
        if not self.verify(warrant, now):
            raise WarrantError("warrant is invalid, expired, changed, or consumed")
        try:
            with self.database.session() as session:
                session.add(
                    ConsumedNonceRow(
                        nonce=warrant.nonce,
                        warrant_id=str(warrant.warrant_id),
                        consumed_at=now,
                    )
                )
        except IntegrityError as exc:
            raise WarrantError("warrant nonce was already consumed") from exc
        return warrant.model_copy(update={"consumed_at": now})

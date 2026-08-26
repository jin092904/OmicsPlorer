"""[T1] Envelope encryption — TenantCipher.

마스터 플랜 §12.2: DEK 는 tenant 당 1개, KEK 로 wrap. 애플리케이션은 평문 KEK 를 절대 보유하지 않는다.
AAD(Additional Authenticated Data) 에 tenant_id, record_id, purpose 를 포함하여 wrong-context decrypt 방지.

본 모듈은 순수 crypto layer — DB 의 tenant_keys 테이블 lookup 은 service 레이어가 담당한다.
TenantCipher 인스턴스는 단일 tenant 의 wrapped DEK 를 들고 있고, 매 encrypt/decrypt 마다
KMS 를 호출하여 plaintext DEK 를 잠시 사용한다 (캐싱은 service 레이어에서 결정).

Algorithm: AES-256-GCM
- Nonce: 12 bytes (random per encryption)
- AAD: canonical JSON (sorted keys) of {**user_aad, "tenant_id": <uuid>}
- Ciphertext: nonce || aes_gcm_ciphertext_with_tag

Threat: T1 (operator plaintext access). KMS audit log 가 모든 decrypt 호출을 기록.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .kms import KmsClient

NONCE_LEN = 12  # AES-GCM 표준


@dataclass(frozen=True)
class EncryptedBlob:
    nonce: bytes
    ciphertext: bytes  # AES-GCM ciphertext + 16-byte tag
    dek_wrapped: bytes  # KMS-wrapped DEK
    kek_key_id: str  # alias 또는 ARN — KMS audit 정합성 보장
    aad: dict[str, str]  # 평문 AAD (감사·재구성용)

    def to_dict(self) -> dict:
        """DB 저장용 직렬화. ciphertext / dek_wrapped 는 BYTEA, aad 는 JSONB."""
        return {
            "nonce": self.nonce,
            "ciphertext": self.ciphertext,
            "dek_wrapped": self.dek_wrapped,
            "kek_key_id": self.kek_key_id,
            "aad": self.aad,
        }


def _canonical_aad_bytes(aad: dict[str, str]) -> bytes:
    """결정론적 직렬화 — 키 정렬, 공백 없음, UTF-8."""
    return json.dumps(aad, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _zero(buf: bytearray) -> None:
    """Best-effort plaintext DEK zero-out. CPython 의 보안 모델로는 완벽하지 않지만,
    적어도 활성 buffer 의 byte 를 덮어쓴다. 외부 메모리 dump 공격 표면 축소."""
    for i in range(len(buf)):
        buf[i] = 0


class TenantCipher:
    """Per-tenant envelope encryption.

    Example:
        cipher = TenantCipher(kms, tenant_id, kek_key_id)
        blob = cipher.encrypt("query text", aad={"record_id": str(uid), "purpose": "saved_query"})
        # 저장: blob.to_dict() → saved_queries.{nonce, ciphertext, dek_wrapped, kek_key_id, aad}
        plain = cipher.decrypt(blob, expected_aad={"record_id": str(uid), "purpose": "saved_query"})
    """

    def __init__(self, kms: KmsClient, tenant_id: UUID, kek_key_id: str) -> None:
        self._kms = kms
        self._tenant_id = tenant_id
        self._kek_key_id = kek_key_id

    def encrypt(self, plaintext: str, aad: dict[str, str]) -> EncryptedBlob:
        full_aad = self._full_aad(aad)
        plaintext_dek, wrapped_dek = self._kms.generate_data_key(self._kek_key_id)
        try:
            nonce = secrets.token_bytes(NONCE_LEN)
            aesgcm = AESGCM(plaintext_dek)
            ciphertext = aesgcm.encrypt(
                nonce, plaintext.encode("utf-8"), _canonical_aad_bytes(full_aad)
            )
        finally:
            # plaintext_dek 은 bytes (immutable) — bytearray 변환 후 zero
            buf = bytearray(plaintext_dek)
            _zero(buf)
            del plaintext_dek
        return EncryptedBlob(
            nonce=nonce,
            ciphertext=ciphertext,
            dek_wrapped=wrapped_dek,
            kek_key_id=self._kek_key_id,
            aad=full_aad,
        )

    def decrypt(self, blob: EncryptedBlob, expected_aad: dict[str, str]) -> str:
        full_expected_aad = self._full_aad(expected_aad)
        # blob 의 AAD 가 expected 와 다르면 즉시 거부 (tenant_id 강제 포함, hot-path AAD 검증)
        if blob.aad != full_expected_aad:
            raise ValueError(
                "AAD mismatch — refusing to decrypt blob with unexpected metadata."
            )
        plaintext_dek = self._kms.decrypt(blob.kek_key_id, blob.dek_wrapped)
        try:
            aesgcm = AESGCM(plaintext_dek)
            plaintext_bytes = aesgcm.decrypt(
                blob.nonce, blob.ciphertext, _canonical_aad_bytes(full_expected_aad)
            )
        finally:
            buf = bytearray(plaintext_dek)
            _zero(buf)
            del plaintext_dek
        return plaintext_bytes.decode("utf-8")

    def _full_aad(self, user_aad: dict[str, str]) -> dict[str, str]:
        """user_aad 에 tenant_id 강제 포함. user_aad 가 tenant_id 를 직접 명시하면 덮어쓴다."""
        return {**user_aad, "tenant_id": str(self._tenant_id)}

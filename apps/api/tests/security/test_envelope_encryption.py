"""[T1] Envelope encryption — round-trip + tamper resistance.

ADR 0002 §CI Gates #3: KMS round-trip + AAD mismatch 거부.

본 파일은 LocalStack KMS (compose service `kms`, http://localhost:4566) 를 요구한다.
KMS 가 reachable 하지 않으면 자동 skip.
"""
from __future__ import annotations

import os
import socket
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag

from src.security.crypto import EncryptedBlob, TenantCipher
from src.security.kms import AwsKmsClient

KEK_ALIAS = "alias/genofinder-tenant-kek-test"


def _kms_reachable() -> bool:
    """Quick TCP probe — port 4566 (LocalStack) accepting connections."""
    host = "localhost"
    port = 4566
    endpoint = os.environ.get("KMS_ENDPOINT_URL")
    if endpoint and endpoint.startswith("http"):
        # http://host:port 파싱
        rest = endpoint.split("://", 1)[1]
        host_part, _, port_part = rest.partition(":")
        host = host_part or "localhost"
        if port_part:
            port_str = port_part.split("/", 1)[0]
            port = int(port_str) if port_str.isdigit() else 4566
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _kms_reachable(), reason="LocalStack KMS not reachable")


@pytest.fixture(scope="module")
def kms() -> AwsKmsClient:
    # 본 파일 단위로 KMS endpoint 를 dev 모드(LocalStack)로 강제
    os.environ.setdefault("KMS_ENDPOINT_URL", "http://localhost:4566")
    return AwsKmsClient()


@pytest.fixture(scope="module")
def kek_id(kms: AwsKmsClient) -> str:
    return kms.ensure_key(KEK_ALIAS, description="test KEK for envelope_encryption suite")


# ---------------------------------------------------------------------------
# 1. Round-trip
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_round_trip(kms: AwsKmsClient, kek_id: str) -> None:
    """평문 → encrypt → decrypt → 원본."""
    tid = uuid4()
    cipher = TenantCipher(kms, tid, kek_id)
    plaintext = "Single-cell RNA-seq of human PBMC, age 18-65"
    aad = {"record_id": "abc-123", "purpose": "saved_query"}

    blob = cipher.encrypt(plaintext, aad)
    assert blob.nonce
    assert len(blob.nonce) == 12
    assert blob.ciphertext
    assert blob.dek_wrapped
    assert blob.aad == {"record_id": "abc-123", "purpose": "saved_query", "tenant_id": str(tid)}

    decrypted = cipher.decrypt(blob, aad)
    assert decrypted == plaintext


def test_encrypt_produces_different_ciphertexts(kms: AwsKmsClient, kek_id: str) -> None:
    """같은 평문·AAD 라도 매번 다른 nonce + 다른 DEK 로 ciphertext 가 달라야 한다 (semantic security)."""
    cipher = TenantCipher(kms, uuid4(), kek_id)
    aad = {"record_id": "x", "purpose": "test"}
    blob1 = cipher.encrypt("same text", aad)
    blob2 = cipher.encrypt("same text", aad)
    assert blob1.nonce != blob2.nonce
    assert blob1.ciphertext != blob2.ciphertext
    assert blob1.dek_wrapped != blob2.dek_wrapped


# ---------------------------------------------------------------------------
# 2. AAD tamper / mismatch — wrong tenant or wrong purpose 시 거부
# ---------------------------------------------------------------------------

def test_decrypt_with_wrong_user_aad_rejected(kms: AwsKmsClient, kek_id: str) -> None:
    """expected_aad 가 다르면 decrypt() 가 즉시 ValueError."""
    cipher = TenantCipher(kms, uuid4(), kek_id)
    blob = cipher.encrypt("secret", aad={"record_id": "r1", "purpose": "saved_query"})

    with pytest.raises(ValueError, match="AAD mismatch"):
        cipher.decrypt(blob, expected_aad={"record_id": "r1", "purpose": "search_log"})


def test_other_tenant_cannot_decrypt(kms: AwsKmsClient, kek_id: str) -> None:
    """다른 tenant 의 cipher 로 decrypt 시도 → AAD mismatch (tenant_id 가 강제 포함되므로)."""
    a_tid = uuid4()
    b_tid = uuid4()
    cipher_a = TenantCipher(kms, a_tid, kek_id)
    cipher_b = TenantCipher(kms, b_tid, kek_id)
    aad = {"record_id": "r1", "purpose": "saved_query"}

    blob = cipher_a.encrypt("A's secret", aad)

    # cipher_b 가 같은 user_aad 로 decrypt 시도 → tenant_id 가 다르므로 mismatch
    with pytest.raises(ValueError, match="AAD mismatch"):
        cipher_b.decrypt(blob, expected_aad=aad)


def test_tampered_ciphertext_rejected(kms: AwsKmsClient, kek_id: str) -> None:
    """ciphertext 가 변조되면 AES-GCM tag 검증이 실패 (InvalidTag)."""
    cipher = TenantCipher(kms, uuid4(), kek_id)
    aad = {"record_id": "r1", "purpose": "saved_query"}
    blob = cipher.encrypt("important", aad)

    # 마지막 byte 한 비트 flip
    tampered = bytearray(blob.ciphertext)
    tampered[-1] ^= 0x01
    bad_blob = EncryptedBlob(
        nonce=blob.nonce, ciphertext=bytes(tampered),
        dek_wrapped=blob.dek_wrapped, kek_key_id=blob.kek_key_id, aad=blob.aad,
    )

    with pytest.raises(InvalidTag):
        cipher.decrypt(bad_blob, expected_aad=aad)


def test_tampered_aad_rejected(kms: AwsKmsClient, kek_id: str) -> None:
    """blob 의 평문 AAD 만 수정해서 expected 와 같게 만들어도, AES-GCM 의 AAD 인증으로 실패."""
    a_tid = uuid4()
    b_tid = uuid4()
    cipher_a = TenantCipher(kms, a_tid, kek_id)
    aad = {"record_id": "r1", "purpose": "saved_query"}
    blob = cipher_a.encrypt("data", aad)

    # AAD 의 tenant_id 만 B 로 위조 (단순 metadata 비교를 우회하려는 시도)
    forged_blob = EncryptedBlob(
        nonce=blob.nonce, ciphertext=blob.ciphertext,
        dek_wrapped=blob.dek_wrapped, kek_key_id=blob.kek_key_id,
        aad={**blob.aad, "tenant_id": str(b_tid)},
    )

    cipher_b = TenantCipher(kms, b_tid, kek_id)
    # 1차 방어: blob.aad vs expected — expected 의 tenant_id=B 와 forged.aad tenant_id=B 가 같아 보이므로 통과
    # 하지만 2차 방어: AES-GCM 이 _canonical_aad_bytes(full_expected_aad)=B 로 검증 시도하나
    # 실제 ciphertext 는 A 의 AAD 로 인증된 상태 → InvalidTag 로 실패
    with pytest.raises(InvalidTag):
        cipher_b.decrypt(forged_blob, expected_aad=aad)


# ---------------------------------------------------------------------------
# 3. 직렬화 / 복원 — DB persistence round-trip 시뮬레이션
# ---------------------------------------------------------------------------

def test_to_dict_round_trip(kms: AwsKmsClient, kek_id: str) -> None:
    """blob.to_dict() → kwargs → 복원 → decrypt 정상."""
    cipher = TenantCipher(kms, uuid4(), kek_id)
    aad = {"record_id": "rid", "purpose": "saved_query"}
    blob = cipher.encrypt("payload", aad)

    persisted = blob.to_dict()
    # DB 에서 다시 읽었다고 가정
    restored = EncryptedBlob(
        nonce=persisted["nonce"], ciphertext=persisted["ciphertext"],
        dek_wrapped=persisted["dek_wrapped"], kek_key_id=persisted["kek_key_id"],
        aad=persisted["aad"],
    )
    assert cipher.decrypt(restored, aad) == "payload"

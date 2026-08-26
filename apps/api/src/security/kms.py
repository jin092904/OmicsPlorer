"""[T1] KMS adapter — envelope encryption 의 KEK 호출 인터페이스.

dev: LocalStack KMS (compose service `kms`, endpoint http://kms:4566)
prod: AWS KMS / GCP KMS / Azure Key Vault (별도 ADR 0005, Week 6 예정)

본 모듈은 평문 KEK 를 절대 보유하지 않는다 — 오직 KMS API 호출만 (마스터 플랜 §12.2).
DEK 는 호출자가 짧게 메모리에 보유하고, 사용 후 삭제한다.
"""
from __future__ import annotations

import os
from typing import Protocol

import boto3
from botocore.config import Config


class KmsClient(Protocol):
    """KMS 추상 인터페이스."""

    def generate_data_key(self, kek_key_id: str) -> tuple[bytes, bytes]:
        """returns (plaintext_dek_32B, ciphertext_blob).

        plaintext_dek 는 호출자가 짧게 사용 후 메모리에서 zero out 해야 한다.
        """

    def decrypt(self, kek_key_id: str, wrapped_dek: bytes) -> bytes:
        """returns plaintext_dek_32B."""


class AwsKmsClient:
    """boto3 기반 KMS client.

    LocalStack 도 동일 인터페이스 — `endpoint_url` 만 다르다.
    `KMS_ENDPOINT_URL` 환경변수가 있으면 dev 모드로 간주.
    """

    def __init__(self, region: str = "us-east-1") -> None:
        endpoint_url = os.environ.get("KMS_ENDPOINT_URL")  # localstack 인 경우 http://kms:4566
        kwargs: dict = {
            "region_name": region,
            "config": Config(retries={"max_attempts": 3, "mode": "standard"}),
        }
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
            # LocalStack 는 dummy credentials 면 충분
            kwargs["aws_access_key_id"] = "test"
            kwargs["aws_secret_access_key"] = "test"  # pragma: allowlist secret
        self._kms = boto3.client("kms", **kwargs)

    def generate_data_key(self, kek_key_id: str) -> tuple[bytes, bytes]:
        resp = self._kms.generate_data_key(KeyId=kek_key_id, KeySpec="AES_256")
        return resp["Plaintext"], resp["CiphertextBlob"]

    def decrypt(self, kek_key_id: str, wrapped_dek: bytes) -> bytes:
        # KeyId 를 명시하면 LocalStack/AWS 가 wrapped_dek 의 ID 와 일치 검증
        resp = self._kms.decrypt(KeyId=kek_key_id, CiphertextBlob=wrapped_dek)
        return resp["Plaintext"]

    def ensure_key(self, alias: str, description: str = "OmicsPlorer KEK") -> str:
        """Idempotent: alias 가 가리키는 key 가 있으면 그 ARN, 없으면 새로 생성.

        dev 부트스트랩에서만 사용. prod 는 IaC(Terraform) 로 사전 프로비저닝.
        반환값은 KEY ID (alias/foo 또는 ARN) — generate_data_key 에 그대로 전달 가능.
        """
        # alias prefix 표준화
        if not alias.startswith("alias/"):
            alias = f"alias/{alias}"
        try:
            self._kms.describe_key(KeyId=alias)
            return alias
        except self._kms.exceptions.NotFoundException:
            pass
        # 새 key + alias 생성
        key = self._kms.create_key(
            Description=description,
            KeyUsage="ENCRYPT_DECRYPT",
            Origin="AWS_KMS",
        )
        key_id = key["KeyMetadata"]["KeyId"]
        self._kms.create_alias(AliasName=alias, TargetKeyId=key_id)
        return alias

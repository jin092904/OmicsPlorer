"""환경 설정.

마스터 플랜 §0.1 에 따라 외부 API rate limit·base URL 등은 코드 상수가 아닌
환경변수 또는 docs/external-apis.md 를 source of truth 로 참조한다.
"""
from __future__ import annotations

# TODO(verify): pydantic-settings 가 본 프로젝트에 추가되면 BaseSettings로 교체.
# 현재는 placeholder만 둔다.

# 다음 키는 .env / .env.example 에 정의되어야 한다:
#   DATABASE_URL                postgresql+asyncpg://...
#   REDIS_URL                   redis://...
#   QDRANT_URL                  http://qdrant:6333
#   OPENSEARCH_URL              http://opensearch:9200
#   OLLAMA_URL                  http://ollama:11434  (internal docker network only)
#   OLLAMA_MODEL_EXTRACTION     (ADR 0004 결정 후 채움)
#   OLLAMA_MODEL_EMBED          (ADR 0004 결정 후 채움)
#   NCBI_EUTILS_API_KEY         optional — 있으면 10rps, 없으면 3rps
#   KMS_PROVIDER                localstack | vault | aws-kms (prod)
#   KMS_KEK_ALIAS               alias/genofinder-tenant-kek
#   APP_TENANT_HEADER           X-Tenant-Id  (Clerk 도입 전 dev only)

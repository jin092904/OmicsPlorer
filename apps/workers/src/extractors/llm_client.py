"""[T2] Ollama HTTP client — local-only LLM wrapper.

ADR 0003 결정에 따라 외부 LLM API 는 호출하지 않는다.
Ollama API (1차 출처: https://github.com/ollama/ollama/blob/main/docs/api.md):
    POST /api/generate   {model, prompt, format='json'|<schema>, stream, options, keep_alive}
    POST /api/chat       {model, messages, tools, format, stream, keep_alive}
    POST /api/embed      {model, input: str | list[str]}

ADR 0002 control:
    T2  외부 LLM SDK import 금지 — httpx 만 사용
    T3  request/response 본문은 일반 로그·OTel span 에 절대 포함하지 않는다 (호출자가 redact)
    T8  generate 결과는 JSON schema 강제 + parse 실패 시 결과 폐기
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_TIMEOUT_S = 60.0


class OllamaClient:
    """Async Ollama HTTP client. 환경변수 우선:
    OLLAMA_URL              (기본 http://localhost:11434)
    OLLAMA_MODEL_EXTRACTION (generate 기본 모델)
    OLLAMA_MODEL_EMBED      (embed 기본 모델)
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        url = base_url or os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
        self._client = client or httpx.AsyncClient(base_url=url, timeout=timeout)
        # ADR 0006: Qwen3 stack 통일. A100 batch 측은 gemma3:27b-it-bf16 으로 env override.
        self._extraction_model = os.environ.get("OLLAMA_MODEL_EXTRACTION", "qwen3:4b")
        self._embed_model = os.environ.get("OLLAMA_MODEL_EMBED", "qwen3-embedding:0.6b")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ---- Embeddings ----

    async def embed(
        self,
        text: str | list[str],
        model: str | None = None,
        truncate_dim: int | None = None,
    ) -> list[list[float]]:
        """입력 문자열(들) → 임베딩(들).

        반환: list[list[float]] — 단일 입력이라도 배열 안에 한 벡터.
        L2-normalized 여부는 모델에 따라 다르다 (nomic-embed-text 는 norm=1.0 — 직접 검증).

        ADR 0006: 인덱싱 시 Qwen3-Embedding-8B 는 native 4096d 를 반환. Matryoshka
        Representation Learning 으로 학습되어 앞부분 [:truncate_dim] 슬라이스가 동일
        의미를 보존한다 (truncate_dim=1024 가 기본 권장). truncate_dim 이 주어지지
        않으면 모델의 native dim 을 그대로 반환.

        검증: 응답이 truncate_dim 보다 짧으면 ValueError — 차원 부족이 의미상 잘못된
        모델 선택일 가능성이 높아 silent pad 보다 명시적 실패가 안전.
        """
        body = {
            "model": model or self._embed_model,
            "input": text,
        }
        resp = await self._client.post("/api/embed", json=body)
        resp.raise_for_status()
        data = resp.json()
        embeddings: list[list[float]] = data["embeddings"]
        if truncate_dim is not None and embeddings:
            native_dim = len(embeddings[0])
            if native_dim < truncate_dim:
                raise ValueError(
                    f"embed response dim {native_dim} is smaller than truncate_dim={truncate_dim} "
                    f"(check OLLAMA_MODEL_EMBED — model 변경 시 EMBED_DIM 갱신 필요)"
                )
            if native_dim > truncate_dim:
                embeddings = [v[:truncate_dim] for v in embeddings]
        return embeddings

    # ---- Generation (구조화 추출용) ----

    async def generate_json(
        self,
        prompt: str,
        schema: dict | None = None,
        model: str | None = None,
        options: dict | None = None,
    ) -> dict:
        """JSON output 강제. schema 가 주어지면 Ollama 의 schema-validated JSON 모드 사용.

        주의:
            - prompt 에 사용자 식별자 / tenant_id 를 포함하지 않는다 (ADR 0003).
            - 호출자는 결과를 jsonschema 등으로 추가 검증해야 한다 (T8).
        """
        body: dict[str, Any] = {
            "model": model or self._extraction_model,
            "prompt": prompt,
            "format": schema if schema is not None else "json",
            "stream": False,
            # gemma4 / qwen3-thinking 등 reasoning-capable 모델은 think tokens 가 응답을
            # 점거해 content 가 빈 채로 끝나는 사례 있음 → 비활성화. 비-reasoning 모델에는 무영향.
            "think": False,
        }
        if options:
            body["options"] = options
        resp = await self._client.post("/api/generate", json=body)
        resp.raise_for_status()
        data = resp.json()
        # Ollama 의 generate 응답은 {response: "<json string>", ...} 형태
        # 모델이 사실상 JSON 문자열을 반환 — 호출자가 json.loads 한다.
        return data

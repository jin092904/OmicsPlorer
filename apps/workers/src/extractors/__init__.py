"""LLM-기반 구조화 추출.

- llm_client.py: Ollama HTTP client wrapper (ADR 0003 T2)
- sanitizer.py: 입력 sanitization (ADR 0002 T8)
- structurer.py: 추출 파이프라인 — JSON schema enforced output

외부 LLM SDK(anthropic, openai, google.generativeai, cohere)는 본 디렉토리에서 import 금지.
infra/lint/no-external-llm.yml 이 이를 강제한다.
"""

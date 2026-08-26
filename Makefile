SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

.PHONY: help dev down logs ps docker-validate docker-build docker-demo docker-models docker-ingest docker-sol4-shadow test test-api test-workers test-web lint lint-py lint-js fmt security-scan migrate alembic-rev clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

dev: ## canonical Docker stack 기동 (빈/full corpus; demo는 make docker-demo)
	./scripts/docker-package.sh up
	@echo "API:        http://localhost:8000"
	@echo "Web:        http://localhost:3000"
	@echo "Postgres:   localhost:5432"
	@echo "Qdrant:     http://localhost:6333"
	@echo "OpenSearch: http://localhost:9200"
	@echo "Ollama:     INTERNAL ONLY (not host-published per ADR 0003)"

docker-validate: ## 모든 canonical Compose profile 정적 검증
	./scripts/docker-package.sh validate

docker-build: ## API/worker/web 이미지 빌드
	./scripts/docker-package.sh build

docker-demo: ## synthetic 12-record demo seed + lexical index + app 기동
	./scripts/docker-package.sh demo

docker-models: ## embedding model을 Ollama volume에 pull
	./scripts/docker-package.sh models

docker-ingest: ## incremental harvest worker/beat profile 기동
	./scripts/docker-package.sh ingest

docker-sol4-shadow: ## DB write 없는 Sol4 self-healing shadow 1회 실행
	./scripts/docker-package.sh sol4-shadow

down: ## docker-compose stop + remove
	./scripts/docker-package.sh down

logs: ## docker-compose 전체 로그 follow
	docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.yml logs -f --tail=200

ps: ## docker-compose 현황
	./scripts/docker-package.sh status

test: test-api test-workers test-web ## 전체 테스트

test-api:
	cd apps/api && uv run pytest

test-workers:
	cd apps/workers && uv run pytest

test-web:
	cd apps/web && pnpm lint && pnpm typecheck && pnpm build

lint: lint-py lint-js ## 전체 lint

lint-py:
	cd apps/api && uv run ruff check .
	cd apps/workers && uv run ruff check .

lint-js:
	cd apps/web && pnpm lint && pnpm typecheck

fmt: ## 자동 포맷팅
	cd apps/api && uv run ruff format .
	cd apps/workers && uv run ruff format .
	cd apps/web && pnpm format

security-scan: ## pip-audit + npm audit + trivy fs + gitleaks
	cd apps/api && uv run pip-audit || true
	cd apps/workers && uv run pip-audit || true
	cd apps/web && pnpm audit --audit-level=critical || true
	command -v trivy >/dev/null && trivy fs --severity CRITICAL,HIGH . || echo "trivy not installed"
	command -v gitleaks >/dev/null && gitleaks detect --source . --no-banner || echo "gitleaks not installed"

migrate: ## Alembic 마이그레이션 적용
	cd apps/api && uv run alembic upgrade head

alembic-rev: ## 새 Alembic revision 생성 (NAME=... 필수)
	@test -n "$(NAME)" || (echo "Usage: make alembic-rev NAME=<short_name>"; exit 1)
	cd apps/api && uv run alembic revision --autogenerate -m "$(NAME)"

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -rf apps/web/.next apps/web/out

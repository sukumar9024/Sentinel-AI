.PHONY: setup dev test lint build compose
setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.lock
	.venv/bin/pip install --no-deps -e .
	npm --prefix frontend ci
	python3 scripts/bootstrap.py
dev:
	python3 scripts/dev.py
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check backend tests scripts
build:
	npm --prefix frontend run build
compose:
	docker compose up --build -d

compose-test:
	.venv/bin/python scripts/compose_smoke.py
backup-restore:
	.venv/bin/python scripts/backup_restore.py
search-restore:
	.venv/bin/python scripts/search_snapshot.py
infra-check:
	terraform -chdir=infrastructure/terraform fmt -check -recursive
	terraform -chdir=infrastructure/terraform init -backend=false
	terraform -chdir=infrastructure/terraform validate

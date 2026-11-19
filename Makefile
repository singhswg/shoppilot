.PHONY: install dev-install lint typecheck test eval run adk-web docker-build docker-run deploy register-registry register-ge clean

PYTHON ?= python3
PORT ?= 8080

install:
	$(PYTHON) -m pip install -e .

dev-install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	ruff check shoppilot app tests

format:
	ruff format shoppilot app tests

typecheck:
	mypy shoppilot app

test:
	pytest --cov=shoppilot --cov=app --cov-report=term-missing

eval:
	adk eval shoppilot evals/holiday_shopping.evalset.json

run:
	uvicorn app.server:app --host 127.0.0.1 --port $(PORT) --reload

adk-web:
	adk web --host 127.0.0.1 --port $(PORT) .

docker-build:
	docker build -t shoppilot:local .

docker-run:
	docker run --rm -p 127.0.0.1:$(PORT):8080 --env-file .env shoppilot:local

deploy:
	./scripts/deploy_cloud_run.sh

register-registry:
	./scripts/register_agent_registry.sh

register-ge:
	./scripts/register_gemini_enterprise.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build *.egg-info

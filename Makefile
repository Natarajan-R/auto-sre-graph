# Makefile
.PHONY: help install dev test lint format docker-build docker-up docker-down clean

help:
	@echo "Available commands:"
	@echo "  install      - Install dependencies"
	@echo "  dev          - Run development server"
	@echo "  test         - Run tests"
	@echo "  lint         - Run linters"
	@echo "  format       - Format code"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-up    - Start Docker Compose"
	@echo "  docker-down  - Stop Docker Compose"
	@echo "  clean        - Clean cache and build artifacts"

install:
	pip install -r requirements/dev.txt
	pre-commit install

dev:
	ENVIRONMENT=DEV \
	uvicorn src.api.webhooks:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --cov=src --cov-report=term-missing

lint:
	ruff check src/ tests/
	black --check src/ tests/
	mypy src/

format:
	black src/ tests/
	ruff --fix src/ tests/

docker-build:
	docker build -t auto-sre-graph:latest -f docker/Dockerfile .

docker-up:
	docker-compose -f docker/docker-compose.yml up -d

docker-down:
	docker-compose -f docker/docker-compose.yml down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
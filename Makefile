.PHONY: help test test-unit test-integration test-coverage lint format clean install dev-install run

# Configuration
PYTHONPATH := .
POETRY := poetry
PYTEST := $(POETRY) run pytest
BLACK := $(POETRY) run black
FLAKE8 := $(POETRY) run flake8
MYPY := $(POETRY) run mypy
PYLINT := $(POETRY) run pylint

# Directories
SRC_DIR := src
TEST_DIR := tests
COVERAGE_DIR := htmlcov

help:
	@echo "Titlis Operator Development Commands"
	@echo ""
	@echo "make install        - Install dependencies"
	@echo "make dev-install    - Install dev dependencies"
	@echo "make test           - Run all tests"
	@echo "make test-unit      - Run unit tests only"
	@echo "make test-integration - Run integration tests (mocked)"
	@echo "make test-coverage  - Run tests with coverage report"
	@echo "make lint           - Run all linters"
	@echo "make format         - Format code with black"
	@echo "make clean          - Clean build artifacts"
	@echo "make run            - Run the operator"

install:
	$(POETRY) install --no-dev

dev-install:
	$(POETRY) install

test: PYTHONPATH=. $(POETRY) run pytest tests/ -v

test-unit:
	PYTHONPATH=. $(PYTEST) tests/unit/ -v

test-integration:
	PYTHONPATH=. $(PYTEST) tests/integration/ -v

test-coverage:
	PYTHONPATH=. $(PYTEST) tests/ \
		--cov=$(SRC_DIR) \
		--cov-report=html:$(COVERAGE_DIR) \
		--cov-report=term \
		--cov-fail-under=70 \
		-v

lint:
	@echo "Running black check..."
	$(BLACK) --check $(SRC_DIR) $(TEST_DIR)
	@echo "Running flake8..."
	$(FLAKE8) $(SRC_DIR) $(TEST_DIR)
	@echo "Running mypy..."
	$(MYPY) $(SRC_DIR)
	@echo "Running pylint..."
	$(PYLINT) $(SRC_DIR)

format:
	$(BLACK) $(SRC_DIR) $(TEST_DIR)

clean:
	rm -rf $(COVERAGE_DIR)
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf *.egg-info
	rm -rf dist
	rm -rf build
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run:
	PYTHONPATH=. $(POETRY) run python src/main.py

# Development quick commands
dev: clean dev-install test lint
	@echo "Development environment ready!"

# Run specific test modules
test-settings:
	PYTHONPATH=. $(PYTEST) tests/unit/test_settings.py -v

test-logging:
	PYTHONPATH=. $(PYTEST) tests/unit/test_logging.py -v

test-datadog:
	PYTHONPATH=. $(PYTEST) tests/unit/test_datadog.py -v

test-slack:
	PYTHONPATH=. $(PYTEST) tests/unit/test_slack.py -v

test-services:
	PYTHONPATH=. $(PYTEST) tests/unit/test_services.py -v

test-controllers:
	PYTHONPATH=. $(PYTEST) tests/unit/test_controllers.py -v

# Quick test with specific pattern
test-pattern:
	PYTHONPATH=. $(PYTEST) tests/ -k $(PATTERN) -v
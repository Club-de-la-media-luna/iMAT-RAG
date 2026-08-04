# Declare all phony targets
.PHONY: install format lint clean test all

# Default target
.DEFAULT_GOAL := all

# Variables
SRC_PROJECT_NAME ?= src
SRC_TESTS ?= tests
FAIL_UNDER ?= 8

UV=uv
UVX=uvx

# Install project dependencies
install:
	@echo "Installing dependencies..."
	@$(UV) sync
	@echo "Dependencies installed! ✅"

# Code formatting
format:
	@echo "Formatting code..."
	@$(UVX) isort .
	@$(UVX) black .
	@echo "Formatting completed! ✅"

# Check code
lint:
	@echo "Running isort..."
	@$(UVX) isort $(SRC_PROJECT_NAME)
	@$(UVX) isort $(SRC_PROJECT_NAME) --check
	@echo "Running Black..."
	@$(UVX) black $(SRC_PROJECT_NAME)
	@$(UVX) black --check $(SRC_PROJECT_NAME)
	@echo "Running Mypy..."
	@$(UV) run mypy $(SRC_PROJECT_NAME) --ignore-missing-imports
	@echo "Running Flake8..."
	@$(UVX) flake8 $(SRC_PROJECT_NAME) --max-line-length 88 --extend-ignore=E203
	@echo "Running Ruff..."
	@$(UVX) ruff check $(SRC_PROJECT_NAME)
	@echo "Running Complexipy..."
	@$(UVX) complexipy $(SRC_PROJECT_NAME) --
	@echo "Running Pylint..."
	@$(UV) run pylint --fail-under=$(FAIL_UNDER) $(SRC_PROJECT_NAME)
	@echo "Lint completed! ✅"

# Clean cache and temporary files
clean:
	@echo "Cleaning cache and temporary files..."
	@find . -type d -name __pycache__ -exec rm -rf {} +
	@find . -type d -name .pytest_cache -exec rm -rf {} +
	@find . -type d -name .mypy_cache -exec rm -rf {} +
	@find . -type d -name .ruff_cache -exec rm -rf {} +
	@find . -type d -name .complexipy_cache -exec rm -rf {} +
	@find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
	@rm -f .coverage
	@echo "Cleaning completed! ✅"

# Test the code (it is assumed tests are in the "tests" folder and start with "test_")
test:
	@echo "Checking if tests directory exists..."
	@if [ -d "$(SRC_TESTS)" ] && [ $$(find $(SRC_TESTS) -name "test_*.py" | wc -l) -gt 0 ]; then \
		echo "Running tests..."; \
		$(UV) run pytest tests -s; \
		echo "Tests passed! ✅"; \
	else \
		echo "No tests directory found or no test files. Skipping tests."; \
	fi

# Run all workflows
all: install format lint test clean
	@echo "All tasks completed! ✅"

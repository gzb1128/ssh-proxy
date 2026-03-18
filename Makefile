.PHONY: test clean install help

# Default target
help:
	@echo "SSH Proxy Manager - Available commands:"
	@echo "  make test       - Run all unit tests"
	@echo "  make test-v     - Run tests with verbose output"
	@echo "  make install    - Install dependencies"
	@echo "  make clean      - Remove cache and compiled files"
	@echo "  make run        - Run the proxy manager"

# Run tests
test:
	@echo "Running tests..."
	python3 run_tests.py

# Run tests with verbose output
test-v:
	@echo "Running tests with verbose output..."
	python3 -m unittest discover -s tests -p "test_*.py" -v

# Install dependencies
install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt

# Clean up cache and compiled files
clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Run the proxy manager
run:
	python3 ssh_proxy.py

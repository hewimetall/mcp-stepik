RUST_CRATES := . packages/mcp-stepik-state

.PHONY: fmt fmt-py fmt-rust lint lint-py lint-rust check test test-py cov-py cov-rust develop

fmt: fmt-py fmt-rust

fmt-py:
	ruff check --fix .
	ruff format .

fmt-rust:
	@set -e; for d in $(RUST_CRATES); do \
		echo "==> rustfmt $$d"; \
		(cd $$d && cargo fmt); \
	done

lint: lint-py lint-rust

lint-py:
	ruff check .
	ruff format --check .
	mypy

lint-rust:
	@set -e; for d in $(RUST_CRATES); do \
		echo "==> rustfmt --check $$d"; \
		(cd $$d && cargo fmt -- --check); \
		echo "==> clippy $$d"; \
		(cd $$d && cargo clippy --all-targets --no-default-features -- -D warnings); \
	done

develop:
	uv sync --extra dev
	(cd packages/mcp-stepik-state && maturin develop)
	maturin develop

check: lint test cov-rust

test: test-py

test-py:
	pytest -q

cov-py:
	pytest -q

cov-rust:
	./scripts/rust-coverage.sh

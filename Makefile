# ==============================================================================
# Installation & Setup
# ==============================================================================

.PHONY: install sync-data lint

# Install dependencies using uv package manager
install:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $$HOME/.local/bin/env; }
	uv sync

# Run periodic pipeline data sync
sync-data:
	cd analytics_pipeline && ./data_pipelines/sync_data.sh

# Run code quality checks (codespell, ruff)
lint:
	uv sync --extra lint
	uv run codespell
	uv run ruff check . --diff
	uv run ruff format . --check --diff
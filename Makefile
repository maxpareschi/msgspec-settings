.PHONY: all venv docs ruff test

all: venv ruff test docs

venv:
	uv sync

docs:
	uv run pdoc -o ./docs --docformat google --favicon assets/msgspec-settings-logo.svg --logo assets/msgspec-settings-logo.svg --search -t ./docs --show-source msgspec_settings

ruff:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest

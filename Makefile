format:
	uv run ruff check
	uv run ruff format

run-tests:
	uv run pytest

update-binder-reqs:
	uv export --no-hashes --format requirements-txt > .binder/requirements.txt

build-docs:
	jupyter-book build docs/
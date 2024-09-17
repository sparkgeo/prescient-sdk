format:
	uv run ruff check

run-tests:
	uv run pytest

update-binder-reqs:
	uv export --no-hashes --format requirements-txt > .binder/requirements.txt

build-docs:
	jupyter-book build docs/
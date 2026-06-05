format:
    uv run ruff check
    uv run ruff format

run-tests:
    uv run pytest

update-binder-reqs:
    uv export --no-hashes --format requirements-txt > .binder/requirements.txt

build-docs:
    jupyter-book build docs/

serve-docs port="8000":
    python -m http.server {{port}} --directory docs/_build/html

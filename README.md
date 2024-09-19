# prescient-sdk
A Python SDK for integrating with Prescient services


# Quickstart

## Local Development

The project is set up using [uv](https://docs.astral.sh/uv/) for package management. To develop locally:

1. Install uv following [these](https://docs.astral.sh/uv/getting-started/installation/) intructions

1. (Optional) Use uv to set up your local env. 

    Note that this will happen automatically when you run tests or any python application using uv, so it is not necessary

    ```
    uv sync
    ```

1. Run the tests

    ```
    uv run pytest
    ```

    or 

    ```
    make run-tests
    ```

## Configuration

Configuration methods are discussed in the Jupyter Notebook [configuration.ipynb](./docs/examples/configuration.ipynb)

## Code Formatting/Linting

Code format is set using the [Ruff](https://docs.astral.sh/ruff/) formatter. To run this formatter:

```
make format
```

## Adding or removing dependencies

Add or remove dependencies using [UV](https://docs.astral.sh/uv/concepts/dependencies/).

In the simplest case, you can add a new dependency like this:

```
uv add <some-dependency>
```

To add a dev dependency:

```
uv add <some-dependency> --dev
```

To remove a dependency:

```
uv remove <some-dependency>
```

For more complex features, see the [uv documentation](https://docs.astral.sh/uv/)

## Build the documentation

Public facing documentation is built using [jupyter-books](https://jupyterbook.org/en/stable/intro.html).

The [docs](./docs) folder contains the layout for the public facing documentation.

You can build the documentation locally, and access the built html pages in a local browser:

1. Build the docs:

    ```
    make build-docs
    ```

1. Open the html in a browser:

    After building the docs, the path to the index.html file will be logged, and should look something like `docs/_build/html/index.html`

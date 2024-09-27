# prescient-sdk

A Python SDK for integrating with Prescient services

SDK Documentation: https://sparkgeo.github.io/prescient-sdk/


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


## Cutting a Release

In order to release a new version to be published to PyPI:

1. Create a new branch from main with the new version as the branch name (v*.*.*) following semantic versioning guidelines.

1. Update the version in [pyproject.toml](./pyproject.toml) under the `[project]` section.

1. Sync the [uv.lock](./uv.lock) file:

    ```
    uv sync
    ```

1. Create a Pull Request against the main branch, have it reviewed and merged.

1. Create a new Release with a tag and title named `v*.*.*`. Include a description of all major updates included in this new release.

    After the release has been created, you should see Actions running to publish the new release to PyPI, and to update the Github Pages documentation.

1. conda-forge release

    Unfortunately, releasing new versions to conda-forge is more involved and less automated. See the conda-forge section below for details.

    
## Conda-forge

This package is available on conda-forge, for comprehensive docs see https://conda-forge.org/docs/maintainer/. In order to release new versions you must already be set as a maintainer of the conda-forge recipe. To become a maintainer follow these instructions: https://conda-forge.org/docs/maintainer/updating_pkgs/#updating-the-maintainer-list

The feedstock repo is located here: https://github.com/conda-forge/prescient-sdk-feedstock

Note that any changes to the feedstock repo need to be made from a fork of that repository, do not create a branch in the repo itself if you need to make manual changes.

### How to update the conda-forge release after PyPI has been updated

conda-forge bots should automatically create a PR in the feedstock repo after a new PYPI version has been released, but it may not contain all changes that you need (e.g. updated dependencies for example).

1. Review the automatically created PR in the feedstock repo, specifically looking at the `meta.yaml` file in the `recipe` folder.

1. To ensure dependencies have been properly updated, it is a good idea to use the [grayskull](https://github.com/conda/grayskull) recipe generator to create an alternate `meta.yaml` file locally and compare it to the the automatically generated version in the feedstock PR.

1. If you want to maintain multiple versions on conda-forge instead of simply keeping the latest version, you may need to manually create a different PR from a different branch, following these instructions: https://conda-forge.org/docs/maintainer/updating_pkgs/#maintaining-several-versions
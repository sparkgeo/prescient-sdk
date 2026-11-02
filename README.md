# prescient-sdk

A Python SDK for the Prescient platform. Use it to search your Organization's STAC catalog, read its data, and run ingestions.

Documentation: https://sparkgeo.github.io/prescient-sdk/

If you used a version before 1.0, read [Migrate to version 1.0](https://sparkgeo.github.io/prescient-sdk/migration.html). Version 1.0 removes the earlier sign-in settings and the S3 upload.

## Install

The SDK needs Python 3.11 or later.

```
pip install prescient-sdk
```

Or from conda-forge:

```
conda install -c conda-forge prescient-sdk
```

## Configure

The SDK signs in with an API key for your Organization. Create the key in the Keycloak Account Console of your Organization, on the **API Keys** page. The key starts with `pk_`.

| Setting | Required | Value |
| --- | --- | --- |
| `prescient_endpoint_url` | Yes | Your Organization host, for example `https://<org>.<env>.prescient.earth` |
| `prescient_api_key` | Yes | Your API key (`pk_...`) |
| `prescient_auth_url` | No | The Keycloak base URL. If you do not set it, the SDK gets it from `prescient_endpoint_url` |

Set the values as environment variables, or put them in a `config.env` file in your working directory:

```
PRESCIENT_ENDPOINT_URL="https://<org>.<env>.prescient.earth"
PRESCIENT_API_KEY="pk_..."
```

Do not commit the file. For other ways to configure the client, see the [configuration example](https://sparkgeo.github.io/prescient-sdk/examples/configuration.html).

## Search the STAC catalog

This example needs `pystac-client`.

```python
from pystac_client import Client

from prescient_sdk import PrescientClient

client = PrescientClient()
catalog = Client.open(client.stac_url, request_modifier=client.request_modifier)
items = list(catalog.search(max_items=10).items())
```

Asset links point at the platform over HTTPS. To read an asset, send the header from `client.headers`. You do not need AWS credentials. The [STAC search example](https://sparkgeo.github.io/prescient-sdk/examples/stac_search.html) shows how to read an asset with rasterio.

## Run an ingestion

You must be an admin of your Organization. The input files must already be in storage: version 1.0 cannot upload files.

```python
from prescient_sdk import IngestClient, IngestResource, IngestSpec
from prescient_sdk.ingest_models import ErrorSeverity, Status

client = IngestClient()
spec = IngestSpec.from_file("spec.yaml")  # a version 2 spec: version: "2.0.0"

ing = IngestResource.create(client, spec)
ing.wait_until_ready()
problems = [e for e in ing.errors() if e.severity != ErrorSeverity.WARNING]
if ing.status is Status.READY and not problems:
    ing.start().wait_until_done()
```

See the [ingest example](https://sparkgeo.github.io/prescient-sdk/examples/ingest.html).

## Local development

The project uses [uv](https://docs.astral.sh/uv/) for package management. Install uv with [these instructions](https://docs.astral.sh/uv/getting-started/installation/).

1. Install the project with its development dependencies:

    ```
    uv sync
    ```

2. Run the tests:

    ```
    uv run pytest
    ```

3. Check and format the code with [Ruff](https://docs.astral.sh/ruff/):

    ```
    uv run ruff check
    uv run ruff format
    ```

### Add or remove dependencies

```
uv add <some-dependency>
uv add <some-dependency> --dev
uv remove <some-dependency>
```

For more, see the [uv documentation](https://docs.astral.sh/uv/concepts/dependencies/).

### Build the documentation

The documentation is a [Jupyter Book](https://jupyterbook.org/en/stable/intro.html) in the [docs](./docs) folder.

1. Build the HTML:

    ```
    uv run jupyter-book build docs/
    ```

2. Open `docs/_build/html/index.html` in a browser.

## Cut a release

1. Make a branch from `main`. Name it with the new version, `vX.Y.Z`, following semantic versioning.

1. Set the version in [pyproject.toml](./pyproject.toml) under `[project]`.

1. Update [uv.lock](./uv.lock):

    ```
    uv sync
    ```

1. Open a pull request against `main`. Get it reviewed and merged.

1. Create a GitHub release with a tag and title `vX.Y.Z`. Describe the main changes.

    The release starts the GitHub Actions that publish to PyPI and update the documentation on GitHub Pages.

1. Release to conda-forge. This step is manual. See the next section.

## Conda-forge

This package is on conda-forge. For the full documentation, see https://conda-forge.org/docs/maintainer/. To release a new version, you must be a maintainer of the conda-forge recipe. To become a maintainer, follow https://conda-forge.org/docs/maintainer/updating_pkgs/#updating-the-maintainer-list

The feedstock repository is https://github.com/conda-forge/prescient-sdk-feedstock

Make changes to the feedstock repository from a fork. Do not create a branch in the repository itself.

### Update the conda-forge release after a PyPI release

A conda-forge bot opens a pull request in the feedstock repository after a new PyPI release. The pull request can miss changes, for example new dependencies.

1. Review the `meta.yaml` file in the `recipe` folder of the bot's pull request.

1. Generate a `meta.yaml` file locally with [grayskull](https://github.com/conda/grayskull). Compare it with the file in the pull request, to check the dependencies.

1. To keep several versions on conda-forge, make a separate pull request from a different branch. Follow https://conda-forge.org/docs/maintainer/updating_pkgs/#maintaining-several-versions

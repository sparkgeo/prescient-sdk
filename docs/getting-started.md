# Getting Started
An SDK for integrating with Prescient services


## Quickstart

### Installation

To use the PrescientSDK, you first need to install it and its dependencies

1. Install or update Python

TODO: check earliest compatible python version
The PrescientClient supports Python 3.8 or later.

For information about how to get the latest version of Python, see the official [Python documentation](https://www.python.org/downloads/).

1. Install PrescientSDK

TODO: update to the correct PyPI name
```
pip install prescientsdk
```

### Configuration




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
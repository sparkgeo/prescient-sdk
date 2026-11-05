# Installation

To use the Prescient SDK, you first need to install it and its dependencies

## 1. Install or update Python

The Prescient SDK supports Python 3.9 or later.

For information about how to get the latest version of Python, see the official [Python documentation](https://www.python.org/downloads/).

## 2. Install Prescient SDK

### From PyPI:

```
pip install prescient-sdk
```

### From conda-forge:

Installing `prescient-sdk` from the `conda-forge` channel can be achieved by adding `conda-forge` to your channels with:

```
conda config --add channels conda-forge
conda config --set channel_priority strict
```

Once the `conda-forge` channel has been enabled, `prescient-sdk` can be installed with `conda`:

```
conda install prescient-sdk
```

or with `mamba`:

```
mamba install prescient-sdk
```

It is possible to list all of the versions of `prescient-sdk` available on your platform with `conda`:

```
conda search prescient-sdk --channel conda-forge
```

or with `mamba`:

```
mamba search prescient-sdk --channel conda-forge
```

Alternatively, `mamba repoquery` may provide more information:

```
# Search all versions available on your platform:
mamba repoquery search prescient-sdk --channel conda-forge

# List packages depending on `prescient-sdk`:
mamba repoquery whoneeds prescient-sdk --channel conda-forge

# List dependencies of `prescient-sdk`:
mamba repoquery depends prescient-sdk --channel conda-forge
```
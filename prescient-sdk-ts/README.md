# prescient-sdk

Polyglot SDK for integrating with Prescient services. Generated from a single TypeScript source using [jsii](https://aws.github.io/jsii/).

## Available packages

| Language | Registry |
| --- | --- |
| TypeScript / JavaScript | npm |
| Python | PyPI |
| C# / .NET | NuGet |
| Java | Maven Central |
| Go | GitHub |

## Development

See [JSII_MIGRATION_PLAN.md](JSII_MIGRATION_PLAN.md) for the full migration plan.

### Prerequisites

All targets require Node.js and pnpm. Each additional language target needs its own toolchain installed and on `PATH`.

| Requirement | Min version | Needed for |
| --- | --- | --- |
| Node.js | 18 | all targets |
| pnpm | 11 | all targets |
| Python 3 | 3.8 | Python wheel |
| Go | 1.18 | Go module |
| .NET SDK | 6.0 | C# / NuGet package |
| JDK | 8 | Java / Maven package |
| Maven | 3.6 | Java / Maven package |

**Node.js + pnpm** — install Node.js from [nodejs.org](https://nodejs.org/), then:

```sh
npm install -g pnpm
```

**Python** — comes pre-installed on most systems. Verify with `python3 --version`.

**Go** — download from [go.dev/dl](https://go.dev/dl/).

**.NET SDK** — follow the [official install guide](https://learn.microsoft.com/en-us/dotnet/core/install/). Verify with `dotnet --version`.

**JDK + Maven** — install a JDK (e.g. via [SDKMAN](https://sdkman.io/): `sdk install java`) and Maven (`sdk install maven`). Verify with `java -version` and `mvn --version`.

To build only the targets whose toolchains are installed, pass `--targets`:

```sh
# build only js and python
pnpm run package -- --targets js,python
```

### Build

```sh
pnpm install
pnpm run build
```

### Package (generate all language targets)

```sh
pnpm run package
```

### Test

```sh
pnpm test
```

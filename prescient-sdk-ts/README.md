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

## Configuration

Copy `config.env` from the repo root and fill in your credentials. The SDK reads it at lowest priority — environment variables always win.

```env
# config.env — see https://sparkgeo.github.io/prescient-sdk/config.html
PRESCIENT_ENDPOINT_URL=https://sparkgeo.prescient.earth
PRESCIENT_AUTH_URL=https://sparkgeo.prescient.earth/oauth2/auth
PRESCIENT_CLIENT_ID=<your-client-id>
PRESCIENT_AUTH_PROVIDER=microsoft        # or google
PRESCIENT_TENANT_ID=<your-tenant-id>     # required for microsoft
# PRESCIENT_GOOGLE_CLIENT_SECRET=...     # required for google (env var only)
```

Three ways to configure the client — all equivalent at runtime:

### File-based (recommended for local development)

| Language | Code |
| --- | --- |
| TypeScript | `new PrescientClient({ envFile: 'config.env' })` |
| Python (jsii) | `PrescientClient(env_file="config.env")` |
| C# / .NET | `new PrescientClient(new PrescientClientOptions { EnvFile = "config.env" })` |
| Java | `new PrescientClient(PrescientClientOptions.builder().envFile("config.env").build())` |
| Go | `prescientsdk.NewPrescientClient(&prescientsdk.PrescientClientOptions{EnvFile: jsii.String("config.env")})` |

All languages funnel through the Node.js jsii runtime, so the file is always read in the same place — no per-language dotenv library needed.

### Environment variables (recommended for CI / containers)

Set `PRESCIENT_*` variables in the process environment, then call the default constructor:

```typescript
// TypeScript — same default-constructor pattern in all languages
const client = new PrescientClient();
```

### Explicit options (useful for testing / multiple clients)

```typescript
const client = new PrescientClient({
  endpointUrl: 'https://sparkgeo.prescient.earth',
  clientId: 'my-client-id',
  authUrl: 'https://sparkgeo.prescient.earth/oauth2/auth',
  tenantId: 'my-tenant-id',
});
```

### Priority order

`explicit options` > `environment variables` > `envFile` > built-in defaults.

### Security note — Google client secret

`PRESCIENT_GOOGLE_CLIENT_SECRET` is intentionally absent from `PrescientClientOptions`. It must be supplied via environment variable or `envFile` — never as a constructor argument — to prevent it from appearing in jsii IPC logs when `JSII_DEBUG=1` is set.

---

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

# prescient-sdk: jsii Migration Plan

Rewrite prescient-sdk as a jsii-compatible TypeScript library. TypeScript is the single source of truth. `jsii-pacmak` generates native packages for Python, C#/.NET, Go, Java, and TypeScript/npm from that single codebase.

## Goal

Replace the Python-only SDK with a polyglot SDK that publishes idiomatic packages for:

| Language | Registry |
|---|---|
| TypeScript / JavaScript | npm |
| Python | PyPI |
| C# / .NET | NuGet |
| Java | Maven Central |
| Go | GitHub (go module) |

---

## Architecture Decisions

### What changes

| Current (Python) | New (TypeScript/jsii) |
|---|---|
| `boto3.Session` return type | **Removed.** Return `BucketCredentials` struct. Each language uses its own AWS SDK. |
| `session` / `upload_session` properties | **Removed.** Breaking change — semver major bump. |
| `auth_credentials: dict` | `AuthCredentials` struct |
| `bucket_credentials: dict` | `BucketCredentials` struct |
| `headers: dict` | `RequestHeaders` struct |
| `str \| Path` params | `string` only |
| `pydantic-settings` | `process.env` + `dotenv` + manual validation |
| `msal` (Python) | `@azure/msal-node` |
| `google-auth-oauthlib` | `google-auth-library` |
| `boto3` STS | `@aws-sdk/client-sts` |
| `boto3` S3 | `@aws-sdk/client-s3` + `@aws-sdk/lib-storage` |
| `requests` | native `fetch` (Node 18+) |

### What stays the same

- Public method/property names (camelCase in TS → snake_case in generated Python, etc.)
- Auth flows: interactive browser OAuth2 (Microsoft + Google)
- AWS STS `AssumeRoleWithWebIdentity` + fileproxy fallback
- Upload logic: recursive directory scan, S3 key construction, overwrite flag
- Configuration via environment variables + `.env` file

### jsii constraints respected

- No `Date` in public API — use ISO 8601 `string` for timestamps
- No index signatures (`[key: string]: unknown`) — use explicit structs
- No `any` / `unknown` return types
- No method overloads
- No generic types beyond `Array<T>`, `Record<string, T>`, `Promise<T>`
- All struct properties `readonly`
- Behavioral interfaces prefixed with `I`; structs must not be
- All non-jsii dependencies in `bundledDependencies`

### Security decisions

- `googleClientSecret` is **not** in `PrescientClientOptions` and never appears in any jsii struct. It must be supplied via `PRESCIENT_GOOGLE_CLIENT_SECRET` environment variable only. Reason: jsii serialises all public struct fields as JSON across the IPC boundary; a struct field would expose the secret in `JSII_DEBUG=1` logs and in consumer code.

---

## Public API

```typescript
// types.ts — all public structs (behavior-free, readonly)

export enum AuthProvider {
  MICROSOFT = 'microsoft',
  GOOGLE = 'google',
}

export interface PrescientClientOptions {
  readonly endpointUrl: string;          // required — HTTPS only
  readonly clientId: string;             // required
  readonly authUrl: string;              // required — HTTPS only
  readonly authProvider?: AuthProvider;  // default MICROSOFT
  readonly tenantId?: string;            // required for MICROSOFT
  readonly googleRedirectPort?: number;  // default 8765
  readonly awsRole?: string;
  readonly awsRegion?: string;
  readonly uploadRole?: string;
  readonly uploadBucket?: string;
  // googleClientSecret intentionally absent — use PRESCIENT_GOOGLE_CLIENT_SECRET env var
}

export interface AuthCredentials {
  readonly idToken: string;
  readonly refreshToken?: string;
  readonly accessToken?: string;
  readonly expiresAt: string; // ISO 8601
}

export interface BucketCredentials {
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
  readonly sessionToken: string;
  readonly expiresAt: string; // ISO 8601
}

export interface RequestHeaders {
  readonly authorization: string;
  readonly contentType: string;
  readonly accept: string;
}

export interface UploadOptions {
  readonly inputDir: string;
  readonly exclude?: string[];
  readonly overwrite?: boolean;
}
```

```typescript
// client.ts

export class PrescientClient {
  constructor(options?: PrescientClientOptions)

  readonly stacCatalogUrl: string
  readonly credentialsExpired: boolean
  readonly authCredentials: AuthCredentials       // lazy, cached, auto-refresh
  readonly headers: RequestHeaders                // derived from authCredentials
  readonly bucketCredentials: BucketCredentials   // lazy, cached, auto-refresh
  readonly uploadBucketCredentials: BucketCredentials

  refreshCredentials(force?: boolean): void
}
```

```typescript
// upload.ts

export function upload(
  options: UploadOptions,
  client?: PrescientClient,
): void
```

---

## Directory Structure

```
prescient-sdk/
├── prescient-sdk-ts/       ← TypeScript source (jsii)
│   ├── src/
│   │   ├── index.ts        ← re-exports everything public
│   │   ├── types.ts        ← all public structs/interfaces
│   │   ├── settings.ts     ← env var loading + validation
│   │   ├── client.ts       ← PrescientClient class
│   │   └── upload.ts       ← upload() function
│   │   └── __tests__/      ← Jest unit tests (64 tests)
│   ├── dist/               ← compiled JS (gitignored)
│   ├── targets/            ← jsii-pacmak output (gitignored)
│   ├── justfile            ← docker smoke-test runner
│   ├── package.json
│   ├── pnpm-workspace.yaml ← nodeLinker: hoisted (required for bundling)
│   └── .gitignore
├── smoke-tests/            ← Docker-based multi-language smoke tests
│   ├── docker-compose.yml
│   ├── docker/             ← Dockerfiles (python, go, dotnet, java)
│   ├── js/smoke.js
│   ├── python/smoke.py
│   ├── go/main.go
│   ├── dotnet/smoke.csproj + src/
│   └── java/pom.xml + src/
└── (original Python SDK files — kept, not deleted)
```

---

## `package.json` (jsii config)

```json
{
  "name": "prescient-sdk",
  "version": "1.0.0",
  "scripts": {
    "build": "jsii",
    "build:watch": "jsii --watch",
    "package": "jsii-pacmak",
    "test": "jest"
  },
  "jsii": {
    "outdir": "targets",
    "targets": {
      "python": { "distName": "prescient-sdk-sparkgeo", "module": "prescient_sdk_sparkgeo" },
      "dotnet": { "namespace": "Sparkgeo.PrescientSdk", "packageId": "Sparkgeo.PrescientSdk" },
      "java": { "package": "com.sparkgeo.prescient", "maven": { "groupId": "com.sparkgeo", "artifactId": "prescient-sdk" } },
      "go": { "moduleName": "github.com/sparkgeo/prescient-sdk-go" }
    }
  },
  "bundledDependencies": [
    "@aws-sdk/client-sts", "@aws-sdk/client-s3", "@aws-sdk/lib-storage",
    "@azure/msal-node", "google-auth-library"
  ]
}
```

> **pnpm note:** `pnpm-workspace.yaml` must contain `nodeLinker: hoisted` so that `pnpm install` places all transitive dependencies at the root `node_modules/`, making them visible to `jsii-pacmak` when it builds the tgz. Without this, only direct deps are bundled (~8 packages vs ~54).

---

## Implementation Phases

### Phase 1 — Scaffold ✅

- [x] Keep existing Python source at repo root (not deleted — new dir approach)
- [x] Create `prescient-sdk-ts/` directory
- [x] Install `jsii`, `jsii-pacmak` as devDeps via pnpm
- [x] Author `package.json` jsii block
- [x] Create `src/index.ts`, `src/types.ts` (shells)
- [x] Verify `jsii` compiles clean

### Phase 2 — Types ✅

- [x] Write all structs/interfaces in `src/types.ts`
- [x] `AuthProvider` enum
- [x] Export all from `src/index.ts`
- [x] `googleClientSecret` absent from `PrescientClientOptions` (env var only)
- [x] Verify jsii accepts every type

### Phase 3 — Settings ✅

- [x] `src/settings.ts`: read `process.env` + optional `.env` via `dotenv`
- [x] `_googleClientSecret` loaded from `PRESCIENT_GOOGLE_CLIENT_SECRET` only (never in Options)
- [x] Validate: MICROSOFT requires `tenantId`; GOOGLE requires `PRESCIENT_GOOGLE_CLIENT_SECRET`
- [x] Unit tests: missing required fields throw, env vars override `.env`

### Phase 4 — PrescientClient ✅

#### 4a — Microsoft auth ✅
- [x] `@azure/msal-node` `PublicClientApplication`
- [x] `acquireTokenInteractive()` for first login
- [x] `acquireTokenByRefreshToken()` for cached refresh token
- [x] Map response → `AuthCredentials` struct

#### 4b — Google auth ✅
- [x] `google-auth-library` `OAuth2Client`
- [x] First login: local HTTP server on `googleRedirectPort`, capture auth code, exchange for tokens
- [x] Refresh: `credentials.refreshAccessToken()`
- [x] Map response → `AuthCredentials` struct

#### 4c — AWS STS + fileproxy ✅
- [x] `@aws-sdk/client-sts` `STSClient` + `AssumeRoleWithWebIdentityCommand`
- [x] fileproxy: `fetch(endpointUrl + 'fileproxy/credentials')` → `BucketCredentials`
- [x] Map STS response → `BucketCredentials`

#### 4d — Credential caching + expiry ✅
- [x] `credentialsExpired`: compare `Date.now()` against `expiresAt` (parsed ISO string)
- [x] `authCredentials` property: lazy init, re-fetch on expiry
- [x] `bucketCredentials` + `uploadBucketCredentials`: same pattern
- [x] `refreshCredentials(force?)`: clear expiration, re-fetch all

#### 4e — Helpers ✅
- [x] `stacCatalogUrl`: `new URL('stac', endpointUrl).href`
- [x] `headers`: derive from `authCredentials.idToken`

### Phase 5 — Upload ✅

- [x] Recursive file scan via Node.js `fs` (no extra dep)
- [x] `_makeS3Key()`: ported from Python logic
- [x] `overwrite=false`: `HeadObjectCommand` check before upload
- [x] Upload: `@aws-sdk/lib-storage` `Upload` (multipart)
- [x] `upload()` function accepts `UploadOptions`, optional `PrescientClient`
- [x] Unit tests: mock S3 with `aws-sdk-client-mock`

### Phase 5.5 — Smoke Test Infrastructure ✅

Docker-based multi-language smoke tests. No local toolchain required beyond Docker.

- [x] `smoke-tests/docker-compose.yml` — 5 services (js, python, go, dotnet, java)
- [x] `smoke-tests/docker/Dockerfile.python` — `python:3.12-slim` + node binary from `node:22-slim`
- [x] `smoke-tests/docker/Dockerfile.go` — `golang:1.25` + node binary from `node:22-slim`
- [x] `smoke-tests/docker/Dockerfile.dotnet` — `mcr.microsoft.com/dotnet/sdk:10.0` + node binary
- [x] `smoke-tests/docker/Dockerfile.java` — `maven:3.9-eclipse-temurin-21` + node binary
- [x] `smoke-tests/js/smoke.js` — JS smoke test
- [x] `smoke-tests/python/smoke.py` — Python smoke test
- [x] `smoke-tests/go/main.go` — Go smoke test
- [x] `smoke-tests/dotnet/` — C# smoke test
- [x] `smoke-tests/java/` — Java smoke test
- [x] `prescient-sdk-ts/justfile` — `just docker` runs all 5; `just docker-build` rebuilds images
- [x] `prescient-sdk-ts/pnpm-workspace.yaml` — `nodeLinker: hoisted` (54 packages bundled)
- [x] `network_mode: host` on all containers — Docker bridge has no internet routing on this host
- [x] All 5 language smoke tests passing

> **jsii runtime note:** All non-JS language runtimes (Python, Go, .NET, Java) spawn a `node` subprocess at runtime. Every container therefore needs Node.js alongside the primary language toolchain. Node binary is copied directly from `node:22-slim` to avoid apt-get/apk DNS failures during build.

### Phase 6 — Tests ✅

- [x] Jest config with `ts-jest` transform
- [x] `src/__tests__/client.test.ts` — mock msal-node + google-auth-library + STS
- [x] `src/__tests__/settings.test.ts` — env var loading, validation errors, secret exclusion from JSON
- [x] `src/__tests__/types.test.ts` — struct shapes, googleClientSecret absence
- [x] `src/__tests__/upload.test.ts` — aws-sdk-client-mock for S3, file scan logic
- [x] 64 tests, 4 suites, all passing

### Phase 7 — CI/CD Pipeline

Update `.github/workflows/ci.yaml`:

```yaml
jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '22' }
      - uses: pnpm/action-setup@v4
        with: { version: '11' }
      - run: pnpm install
      - run: pnpm run build        # jsii
      - run: pnpm test             # jest

  package:
    needs: build-and-test
    runs-on: ubuntu-latest
    steps:
      - run: pnpm run package      # jsii-pacmak → targets/

  publish-npm:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: package
    steps:
      - run: pnpm publish

  publish-pypi:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: package
    steps:
      - uses: actions/setup-python@v5
      - run: pip install twine && twine upload targets/python/dist/*

  publish-nuget:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: package
    steps:
      - uses: actions/setup-dotnet@v4
      - run: dotnet nuget push targets/dotnet/*.nupkg

  publish-maven:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: package
    steps:
      - uses: actions/setup-java@v4
      - run: mvn deploy -f targets/java/pom.xml

  publish-go:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: package
    steps:
      - run: |
          cd targets/go
          git tag && git push  # go modules published via git tags
          # Requires sparkgeo/prescient-sdk-go repo to exist on GitHub
```

> **Infrastructure prerequisite:** Create `sparkgeo/prescient-sdk-go` GitHub repo for Go module publishing before running publish-go.

---

## Effort Summary

| Phase | Days | Status |
|---|---|---|
| 1 — Scaffold | 0.5 | ✅ Done |
| 2 — Types | 0.5 | ✅ Done |
| 3 — Settings | 0.5 | ✅ Done |
| 4 — PrescientClient | 4.0 | ✅ Done |
| 5 — Upload | 1.0 | ✅ Done |
| 5.5 — Smoke Test Infrastructure | 1.0 | ✅ Done |
| 6 — Tests | 1.5 | ✅ Done |
| 7 — CI/CD | 1.0 | Not started |
| **Total** | **~10 days** | |

---

## Breaking Changes (semver major → v1.0.0)

- `session` property removed — use `bucketCredentials` + language-native AWS SDK
- `upload_session` property removed — same
- `auth_credentials` / `bucket_credentials` return typed structs, not dicts
- Python import path: `prescient_sdk_sparkgeo` (was `prescient_sdk`)
- `Path` objects no longer accepted — use `str` / `string`
- `googleClientSecret` never accepted as a constructor argument — use env var

---

## Prerequisites

Before starting Phase 7:

- Create `sparkgeo/prescient-sdk-go` GitHub repo for Go module publishing
- Configure npm, PyPI, NuGet, and Maven credentials in GitHub Actions secrets
- Node.js 22, pnpm 11 available in CI

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

---

## Public API

```typescript
// types.ts — all public structs (behavior-free, readonly)

export interface PrescientClientOptions {
  readonly envFile?: string;
  readonly endpointUrl?: string;
  readonly authProvider?: 'microsoft' | 'google';
  readonly clientId?: string;
  readonly authUrl?: string;
  readonly tenantId?: string;
  readonly googleClientSecret?: string;
  readonly googleRedirectPort?: number;
  readonly awsRole?: string;
  readonly awsRegion?: string;
  readonly uploadRole?: string;
  readonly uploadBucket?: string;
}

export interface AuthCredentials {
  readonly idToken: string;
  readonly refreshToken?: string;
  readonly accessToken?: string;
  readonly expiration: string; // ISO 8601
}

export interface BucketCredentials {
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
  readonly sessionToken: string;
  readonly expiration: string; // ISO 8601
}

export interface RequestHeaders {
  readonly authorization: string;
  readonly contentType: string;
  readonly accept: string;
}

export interface UploadOptions {
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
  inputDir: string,
  options?: UploadOptions,
  client?: PrescientClient,
): void
```

---

## Directory Structure

```
prescient-sdk/
├── src/
│   ├── index.ts        ← re-exports everything public
│   ├── types.ts        ← all public structs/interfaces
│   ├── settings.ts     ← env var loading + validation
│   ├── client.ts       ← PrescientClient class
│   └── upload.ts       ← upload() function
├── test/
│   ├── client.test.ts
│   ├── settings.test.ts
│   └── upload.test.ts
├── dist/               ← compiled JS (gitignored)
├── targets/            ← jsii-pacmak output (gitignored)
├── package.json
├── tsconfig.json       ← jsii-managed (do not edit manually)
└── .gitignore
```

---

## `package.json` (jsii config)

```json
{
  "name": "prescient-sdk",
  "version": "1.0.0",
  "description": "Polyglot SDK for integrating with Prescient services",
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "scripts": {
    "build": "jsii",
    "build:watch": "jsii --watch",
    "package": "jsii-pacmak",
    "test": "jest"
  },
  "stability": "stable",
  "jsii": {
    "outdir": "targets",
    "targets": {
      "python": {
        "distName": "prescient-sdk",
        "module": "prescient_sdk"
      },
      "dotnet": {
        "namespace": "Sparkgeo.PrescientSdk",
        "packageId": "Sparkgeo.PrescientSdk"
      },
      "java": {
        "package": "com.sparkgeo.prescient",
        "maven": {
          "groupId": "com.sparkgeo",
          "artifactId": "prescient-sdk"
        }
      },
      "go": {
        "moduleName": "github.com/sparkgeo/prescient-sdk-go"
      }
    },
    "tsc": {
      "outDir": "dist"
    }
  },
  "bundledDependencies": [
    "@aws-sdk/client-sts",
    "@aws-sdk/client-s3",
    "@aws-sdk/lib-storage",
    "@azure/msal-node",
    "google-auth-library",
    "dotenv"
  ],
  "dependencies": {
    "@aws-sdk/client-sts": "^3",
    "@aws-sdk/client-s3": "^3",
    "@aws-sdk/lib-storage": "^3",
    "@azure/msal-node": "^2",
    "google-auth-library": "^9",
    "dotenv": "^16"
  },
  "devDependencies": {
    "@types/node": "^18",
    "aws-sdk-client-mock": "^4",
    "jest": "^29",
    "jsii": "^5",
    "jsii-pacmak": "^1",
    "ts-jest": "^29",
    "typescript": "~5.4"
  }
}
```

---

## Implementation Phases

### Phase 1 — Scaffold (0.5 days)

- [ ] Delete existing Python source (`prescient_sdk/`, `tests/`, `pyproject.toml`, `uv.lock`)
- [ ] `npm init` + install `jsii`, `jsii-pacmak` as devDeps
- [ ] Run `npx jsii-config` or manually author `package.json` jsii block (see above)
- [ ] Create `src/index.ts`, `src/types.ts` (empty shells)
- [ ] Verify `npx jsii` compiles clean on empty project

### Phase 2 — Types (0.5 days)

- [ ] Write all structs/interfaces in `src/types.ts`
- [ ] Export all from `src/index.ts`
- [ ] Verify jsii accepts every type (no index signatures, no unions as return types)

### Phase 3 — Settings (0.5 days)

- [ ] `src/settings.ts`: read `process.env` + optional `.env` file via `dotenv`
- [ ] Validate: `microsoft` provider requires `tenantId`; `google` requires `googleClientSecret`
- [ ] Return validated `PrescientClientOptions` — not a class, internal helper only
- [ ] Unit tests: missing required fields throw, env vars override `.env`

### Phase 4 — PrescientClient (4 days)

#### 4a — Microsoft auth (1 day)
- `@azure/msal-node` `PublicClientApplication`
- `acquireTokenInteractive()` for first login (opens browser)
- `acquireTokenByRefreshToken()` for cached refresh token
- Map response → `AuthCredentials` struct

#### 4b — Google auth (1.5 days)
- `google-auth-library` `OAuth2Client`
- First login: spin up local HTTP server on `googleRedirectPort`, redirect user to consent URL, capture auth code, exchange for tokens
- Refresh: `credentials.refreshAccessToken()`
- Map response → `AuthCredentials` struct

  > Note: This is more involved than Python's `InstalledAppFlow.run_local_server()`.
  > Requires a manual `http.createServer` + Promise wrapper for the auth code callback.

#### 4c — AWS STS + fileproxy (0.5 days)
- `@aws-sdk/client-sts` `STSClient` + `AssumeRoleWithWebIdentityCommand`
- fileproxy: `fetch(endpointUrl + 'fileproxy/credentials')` → map snake_case → `BucketCredentials`
- Map STS response → `BucketCredentials` (PascalCase → camelCase)

#### 4d — Credential caching + expiry (0.5 days)
- `credentialsExpired`: compare `Date.now()` against `AuthCredentials.expiration` (parsed ISO string)
- `authCredentials` property: lazy init, re-fetch on expiry
- `bucketCredentials` + `uploadBucketCredentials`: same pattern
- `refreshCredentials(force?)`: clear expiration, re-fetch all

#### 4e — Helpers (0.5 days)
- `stacCatalogUrl`: `new URL('stac', endpointUrl).href`
- `headers`: derive from `authCredentials.idToken`

### Phase 5 — Upload (1 day)

- [ ] Recursive file scan: `fast-glob` (bundled) or Node.js `fs.readdirSync` recursive
- [ ] `_makeS3Key()`: port Python logic exactly
- [ ] `overwrite=false`: `HeadObjectCommand` check before upload
- [ ] Upload: `@aws-sdk/lib-storage` `Upload` (handles multipart automatically)
- [ ] `upload()` function: accepts `inputDir`, `UploadOptions`, optional `PrescientClient`
- [ ] Unit tests: mock S3 client with `aws-sdk-client-mock`

### Phase 6 — Tests (1.5 days)

- [ ] Jest config (`jest.config.js`) with `ts-jest` transform
- [ ] `client.test.ts`: mock `msal-node` + `google-auth-library` + STS client
- [ ] `settings.test.ts`: env var loading, validation errors
- [ ] `upload.test.ts`: `aws-sdk-client-mock` for S3, file scan logic
- [ ] CI smoke tests: instantiate generated Python client in a separate test job

### Phase 7 — CI/CD Pipeline (1 day)

Update `.github/workflows/ci.yaml`:

```yaml
jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npm run build        # npx jsii
      - run: npm test             # jest

  package:
    needs: build-and-test
    runs-on: ubuntu-latest
    steps:
      - run: npm run package      # npx jsii-pacmak → targets/

  publish-npm:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: package
    steps:
      - run: npm publish

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
          git tag && git push  # go modules are published via git tags
```

---

## Effort Summary

| Phase | Days |
|---|---|
| 1 — Scaffold | 0.5 |
| 2 — Types | 0.5 |
| 3 — Settings | 0.5 |
| 4 — PrescientClient | 4.0 |
| 5 — Upload | 1.0 |
| 6 — Tests | 1.5 |
| 7 — CI/CD | 1.0 |
| **Total** | **~9 days** |

---

## Breaking Changes (semver major → v1.0.0)

- `session` property removed — use `bucketCredentials` + language-native AWS SDK
- `upload_session` property removed — same
- `auth_credentials` / `bucket_credentials` return typed structs, not dicts
- Python import path unchanged (`import prescient_sdk`) but internals differ
- `Path` objects no longer accepted — use `str` / `string`

---

## Prerequisites

Before starting Phase 1, ensure available locally:

- Node.js 18, 20, or 22
- .NET ≥ 6.0 (for dotnet target)
- Go ≥ 1.21 (for go target)
- JDK ≥ 8 + Maven ≥ 3.6 (for java target)
- Python ≥ 3.9 (for python target smoke tests)

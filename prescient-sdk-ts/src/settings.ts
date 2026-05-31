import * as fs from 'fs';
import { AuthProvider, PrescientClientOptions } from './types';

/**
 * Resolved, validated settings for PrescientClient.
 *
 * Constructed from {@link PrescientClientOptions}, `PRESCIENT_*` environment
 * variables, and/or a `config.env` file (via `opts.envFile`). Validation
 * enforces HTTPS on all URL fields and requires provider-specific fields.
 *
 * Resolution priority (highest first):
 * 1. Explicit `PrescientClientOptions` fields
 * 2. `PRESCIENT_*` environment variables
 * 3. `envFile` values (if `opts.envFile` is set)
 * 4. Built-in defaults
 *
 * Environment variable → field mapping:
 * ```
 * PRESCIENT_ENDPOINT_URL          → endpointUrl
 * PRESCIENT_AUTH_PROVIDER         → authProvider
 * PRESCIENT_CLIENT_ID             → clientId
 * PRESCIENT_AUTH_URL              → authUrl
 * PRESCIENT_TENANT_ID             → tenantId
 * PRESCIENT_GOOGLE_CLIENT_SECRET  → _googleClientSecret  (never in Options struct)
 * PRESCIENT_GOOGLE_REDIRECT_PORT  → googleRedirectPort
 * PRESCIENT_AWS_ROLE              → awsRole
 * PRESCIENT_AWS_REGION            → awsRegion
 * PRESCIENT_UPLOAD_ROLE           → uploadRole
 * PRESCIENT_UPLOAD_BUCKET         → uploadBucket
 * ```
 */
export class Settings {
  readonly endpointUrl: string;
  readonly authProvider: AuthProvider;
  readonly clientId: string;
  readonly authUrl: string;
  readonly tenantId?: string;
  /** @internal Never exposed in PrescientClientOptions — read from env only. */
  readonly _googleClientSecret?: string;
  readonly googleRedirectPort: number;
  readonly awsRole?: string;
  readonly awsRegion?: string;
  readonly uploadRole?: string;
  readonly uploadBucket?: string;

  constructor(opts?: PrescientClientOptions) {
    const env = process.env;
    const fileEnv: Record<string, string> = opts?.envFile
      ? Settings.parseEnvFile(opts.envFile)
      : {};

    this.endpointUrl =
      opts?.endpointUrl ?? env['PRESCIENT_ENDPOINT_URL'] ?? fileEnv['PRESCIENT_ENDPOINT_URL'] ?? '';
    this.authProvider = resolveAuthProvider(
      opts?.authProvider,
      env['PRESCIENT_AUTH_PROVIDER'],
      fileEnv['PRESCIENT_AUTH_PROVIDER'],
    );
    this.clientId =
      opts?.clientId ?? env['PRESCIENT_CLIENT_ID'] ?? fileEnv['PRESCIENT_CLIENT_ID'] ?? '';
    this.authUrl =
      opts?.authUrl ?? env['PRESCIENT_AUTH_URL'] ?? fileEnv['PRESCIENT_AUTH_URL'] ?? '';
    this.tenantId =
      opts?.tenantId ?? env['PRESCIENT_TENANT_ID'] ?? fileEnv['PRESCIENT_TENANT_ID'];
    this._googleClientSecret =
      env['PRESCIENT_GOOGLE_CLIENT_SECRET'] ?? fileEnv['PRESCIENT_GOOGLE_CLIENT_SECRET'];
    this.googleRedirectPort = resolvePort(
      opts?.googleRedirectPort,
      env['PRESCIENT_GOOGLE_REDIRECT_PORT'],
      fileEnv['PRESCIENT_GOOGLE_REDIRECT_PORT'],
    );
    this.awsRole = opts?.awsRole ?? env['PRESCIENT_AWS_ROLE'] ?? fileEnv['PRESCIENT_AWS_ROLE'];
    this.awsRegion =
      opts?.awsRegion ?? env['PRESCIENT_AWS_REGION'] ?? fileEnv['PRESCIENT_AWS_REGION'];
    this.uploadRole =
      opts?.uploadRole ?? env['PRESCIENT_UPLOAD_ROLE'] ?? fileEnv['PRESCIENT_UPLOAD_ROLE'];
    this.uploadBucket =
      opts?.uploadBucket ?? env['PRESCIENT_UPLOAD_BUCKET'] ?? fileEnv['PRESCIENT_UPLOAD_BUCKET'];

    this.validate();
  }

  /**
   * Parses a `KEY=VALUE` env file. Lines starting with `#` and blank lines
   * are skipped. Values may optionally be wrapped in single or double quotes.
   */
  private static parseEnvFile(filePath: string): Record<string, string> {
    let content: string;
    try {
      content = fs.readFileSync(filePath, 'utf-8');
    } catch {
      throw new Error(`envFile not found or unreadable: "${filePath}". Check the path and try again.`);
    }
    const result: Record<string, string> = {};
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx === -1) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      if (!key) continue;
      let value = trimmed.slice(eqIdx + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      result[key] = value;
    }
    return result;
  }

  private validate(): void {
    if (!this.endpointUrl) {
      throw new Error(
        'endpointUrl is required. Set PRESCIENT_ENDPOINT_URL or pass endpointUrl in options.',
      );
    }
    assertHttps(this.endpointUrl, 'endpointUrl');
    assertNotSsrf(this.endpointUrl, 'endpointUrl');

    if (!this.clientId) {
      throw new Error(
        'clientId is required. Set PRESCIENT_CLIENT_ID or pass clientId in options.',
      );
    }

    if (!this.authUrl) {
      throw new Error(
        'authUrl is required. Set PRESCIENT_AUTH_URL or pass authUrl in options.',
      );
    }
    assertHttps(this.authUrl, 'authUrl');
    assertNotSsrf(this.authUrl, 'authUrl');

    if (this.authProvider === AuthProvider.MICROSOFT && !this.tenantId) {
      throw new Error(
        'tenantId is required when authProvider is MICROSOFT. ' +
          'Set PRESCIENT_TENANT_ID or pass tenantId in options.',
      );
    }

    if (this.authProvider === AuthProvider.GOOGLE && !this._googleClientSecret) {
      throw new Error(
        'PRESCIENT_GOOGLE_CLIENT_SECRET env var is required when authProvider is GOOGLE.',
      );
    }

    if (this.awsRole !== undefined) {
      if (!this.awsRole.startsWith('arn:') || this.awsRole.length > 2048) {
        throw new Error(
          `awsRole must be a valid AWS ARN (e.g. arn:aws:iam::123456789012:role/MyRole). ` +
            `Received: "${this.awsRole}".`,
        );
      }
    }
  }

  /**
   * Returns a JSON-safe representation that excludes `_googleClientSecret`.
   * Called automatically by `JSON.stringify()`.
   */
  toJSON(): PrescientClientOptions {
    return {
      endpointUrl: this.endpointUrl,
      authProvider: this.authProvider,
      clientId: this.clientId,
      authUrl: this.authUrl,
      tenantId: this.tenantId,
      googleRedirectPort: this.googleRedirectPort,
      awsRole: this.awsRole,
      awsRegion: this.awsRegion,
      uploadRole: this.uploadRole,
      uploadBucket: this.uploadBucket,
    };
  }
}

function resolveAuthProvider(
  fromOpts: AuthProvider | undefined,
  fromEnv: string | undefined,
  fromFile: string | undefined,
): AuthProvider {
  if (fromOpts !== undefined) return fromOpts;
  const raw = fromEnv ?? fromFile;
  if (raw === undefined) return AuthProvider.MICROSOFT;
  const lower = raw.toLowerCase();
  if (lower === 'google') return AuthProvider.GOOGLE;
  if (lower === 'microsoft') return AuthProvider.MICROSOFT;
  throw new Error(
    `Invalid PRESCIENT_AUTH_PROVIDER value "${raw}". Must be "microsoft" or "google".`,
  );
}

function resolvePort(
  fromOpts: number | undefined,
  fromEnv: string | undefined,
  fromFile: string | undefined,
): number {
  if (fromOpts !== undefined) {
    if (!Number.isInteger(fromOpts) || fromOpts < 1 || fromOpts > 65535) {
      throw new Error(`googleRedirectPort must be an integer 1–65535. Received: ${fromOpts}.`);
    }
    return fromOpts;
  }
  const raw = fromEnv ?? fromFile;
  if (raw === undefined) return 8765;
  const n = parseInt(raw, 10);
  if (isNaN(n) || n < 1 || n > 65535 || String(n) !== raw.trim()) {
    throw new Error(
      `Invalid PRESCIENT_GOOGLE_REDIRECT_PORT value "${raw}". Must be an integer 1–65535.`,
    );
  }
  return n;
}

function assertHttps(url: string, field: string): void {
  if (!url.startsWith('https://')) {
    let display: string;
    try {
      display = new URL(url).origin;
    } catch {
      display = '<invalid URL>';
    }
    throw new Error(
      `${field} must be an HTTPS URL. Received: "${display}". ` +
        'HTTP is not supported — credentials would be transmitted in plaintext.',
    );
  }
}

const SSRF_BLOCKED_HOSTS = new Set(['localhost', '0.0.0.0', '[::1]', '169.254.169.254']);

function assertNotSsrf(url: string, field: string): void {
  let host: string;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    throw new Error(`${field} is not a valid URL.`);
  }
  if (SSRF_BLOCKED_HOSTS.has(host)) {
    throw new Error(
      `${field} must not target internal infrastructure. "${host}" is not allowed.`,
    );
  }
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (ipv4) {
    const a = parseInt(ipv4[1], 10);
    const b = parseInt(ipv4[2], 10);
    if (
      a === 10 ||
      a === 127 ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168)
    ) {
      throw new Error(
        `${field} must not target internal infrastructure. "${host}" is a private/loopback address.`,
      );
    }
  }
}

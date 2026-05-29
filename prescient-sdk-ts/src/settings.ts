import { AuthProvider, PrescientClientOptions } from './types';

/**
 * Resolved, validated settings for PrescientClient.
 *
 * Constructed either from a {@link PrescientClientOptions} struct or from
 * `PRESCIENT_*` environment variables (falling back to a `config.env` file
 * if `dotenv` is loaded by the consumer). Validation enforces HTTPS on all
 * URL fields and requires provider-specific fields.
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

    this.endpointUrl = opts?.endpointUrl ?? env['PRESCIENT_ENDPOINT_URL'] ?? '';
    this.authProvider = resolveAuthProvider(
      opts?.authProvider,
      env['PRESCIENT_AUTH_PROVIDER'],
    );
    this.clientId = opts?.clientId ?? env['PRESCIENT_CLIENT_ID'] ?? '';
    this.authUrl = opts?.authUrl ?? env['PRESCIENT_AUTH_URL'] ?? '';
    this.tenantId = opts?.tenantId ?? env['PRESCIENT_TENANT_ID'];
    this._googleClientSecret = env['PRESCIENT_GOOGLE_CLIENT_SECRET'];
    this.googleRedirectPort = resolvePort(
      opts?.googleRedirectPort,
      env['PRESCIENT_GOOGLE_REDIRECT_PORT'],
    );
    this.awsRole = opts?.awsRole ?? env['PRESCIENT_AWS_ROLE'];
    this.awsRegion = opts?.awsRegion ?? env['PRESCIENT_AWS_REGION'];
    this.uploadRole = opts?.uploadRole ?? env['PRESCIENT_UPLOAD_ROLE'];
    this.uploadBucket = opts?.uploadBucket ?? env['PRESCIENT_UPLOAD_BUCKET'];

    this.validate();
  }

  private validate(): void {
    if (!this.endpointUrl) {
      throw new Error(
        'endpointUrl is required. Set PRESCIENT_ENDPOINT_URL or pass endpointUrl in options.',
      );
    }
    assertHttps(this.endpointUrl, 'endpointUrl');

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
  }
}

function resolveAuthProvider(
  fromOpts: AuthProvider | undefined,
  fromEnv: string | undefined,
): AuthProvider {
  if (fromOpts !== undefined) return fromOpts;
  if (fromEnv === undefined) return AuthProvider.MICROSOFT;
  const lower = fromEnv.toLowerCase();
  if (lower === 'google') return AuthProvider.GOOGLE;
  if (lower === 'microsoft') return AuthProvider.MICROSOFT;
  throw new Error(
    `Invalid PRESCIENT_AUTH_PROVIDER value "${fromEnv}". Must be "microsoft" or "google".`,
  );
}

function resolvePort(fromOpts: number | undefined, fromEnv: string | undefined): number {
  if (fromOpts !== undefined) return fromOpts;
  if (fromEnv === undefined) return 8765;
  const n = Number(fromEnv);
  if (!Number.isInteger(n) || n < 1 || n > 65535) {
    throw new Error(
      `Invalid PRESCIENT_GOOGLE_REDIRECT_PORT value "${fromEnv}". Must be an integer 1–65535.`,
    );
  }
  return n;
}

function assertHttps(url: string, field: string): void {
  if (!url.startsWith('https://')) {
    throw new Error(
      `${field} must be an HTTPS URL. Received: "${url}". ` +
        'HTTP is not supported — credentials would be transmitted in plaintext.',
    );
  }
}

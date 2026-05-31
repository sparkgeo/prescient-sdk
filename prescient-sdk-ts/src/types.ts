/** OAuth2 authentication provider. */
export enum AuthProvider {
  MICROSOFT = 'microsoft',
  GOOGLE = 'google',
}

/**
 * Configuration options for PrescientClient.
 *
 * All fields map 1-to-1 with the PRESCIENT_* environment variables.
 * The Google client secret is intentionally absent — it must be supplied
 * via the PRESCIENT_GOOGLE_CLIENT_SECRET environment variable to avoid
 * leaking it across the jsii IPC boundary and into process logs.
 */
export interface PrescientClientOptions {
  /**
   * Base URL of the Prescient API endpoint.
   * @remarks Must be an HTTPS URL. HTTP is not supported and will be rejected
   * at client initialization.
   */
  readonly endpointUrl: string;

  /** OAuth2 authentication provider. Defaults to MICROSOFT. */
  readonly authProvider?: AuthProvider;

  /** OAuth2 client ID issued by the selected authentication provider. */
  readonly clientId: string;

  /**
   * OAuth2 token endpoint base URL.
   * @remarks Must be an HTTPS URL. HTTP is not supported and will be rejected
   * at client initialization.
   */
  readonly authUrl: string;

  /** Microsoft Entra tenant ID. Required when authProvider is MICROSOFT. */
  readonly tenantId?: string;

  /**
   * Loopback port for the Google OAuth2 redirect URI.
   * Defaults to 8765. Set to the registered port for Web-app OAuth clients.
   */
  readonly googleRedirectPort?: number;

  /**
   * AWS IAM role ARN for STS credential exchange.
   * When unset, credentials are fetched from the /fileproxy/credentials endpoint.
   */
  readonly awsRole?: string;

  /** AWS region used when assuming awsRole. Required only when awsRole is set. */
  readonly awsRegion?: string;

  /** AWS IAM role ARN used by upload helpers to write to the upload bucket. */
  readonly uploadRole?: string;

  /** AWS S3 bucket name targeted by the upload helpers. */
  readonly uploadBucket?: string;
}

/**
 * OAuth2 credentials returned after a successful authentication flow.
 * expiresAt is an ISO 8601 UTC timestamp.
 */
export interface AuthCredentials {
  readonly idToken: string;
  /**
   * Long-lived OAuth2 refresh token. Unlike `idToken` and `accessToken`
   * (minutes-to-hours TTL), refresh tokens are valid for days-to-months and
   * silently obtain new access tokens without user interaction.
   *
   * @remarks **Security:** Do not log this value. For Google OAuth2 it is
   * issued only once at initial consent — if leaked the user must re-authorize.
   * jsii serialises all public struct fields as JSON across the IPC boundary;
   * enabling `JSII_DEBUG=1` will expose this token in plaintext logs.
   * Prefer keeping this token in private client state rather than exposing it
   * to consumer code.
   */
  readonly refreshToken?: string;
  readonly accessToken?: string;
  /** ISO 8601 UTC timestamp at which these credentials expire. */
  readonly expiresAt: string;
}

/**
 * Temporary AWS credentials for S3 access.
 *
 * Use these to construct a native AWS SDK client in the target language,
 * then discard this object immediately — do not retain it, serialize it,
 * or pass it through logging frameworks.
 *
 * jsii serializes all public struct fields as JSON across the IPC boundary;
 * enabling `JSII_DEBUG=1` or any debug-level object serialization will expose
 * `secretAccessKey` and `sessionToken` in plaintext logs.
 *
 * Python:  boto3.Session(aws_access_key_id=creds.access_key_id, ...)
 * Node.js: new S3Client({ credentials: { accessKeyId: creds.accessKeyId, ... } })
 * Go:      aws.NewCredentialsCache(...)
 * C#:      new SessionAWSCredentials(...)
 */
export interface BucketCredentials {
  readonly accessKeyId: string;
  /**
   * @remarks **Security:** Do not log. Discard immediately after constructing
   * the native AWS SDK client. Treat with the same care as a password.
   */
  readonly secretAccessKey: string;
  /**
   * @remarks **Security:** Do not log. Discard immediately after constructing
   * the native AWS SDK client.
   */
  readonly sessionToken: string;
  /** ISO 8601 UTC timestamp at which these credentials expire. */
  readonly expiresAt: string;
}

/** HTTP request headers used when calling the Prescient API. */
export interface RequestHeaders {
  readonly contentType: string;
  readonly accept: string;
  /**
   * Bearer token for authenticating to the Prescient API.
   * Format: `"Bearer <id_token>"`
   *
   * @remarks **Security:** This field contains a full bearer token. Possessing
   * it is equivalent to being authenticated as the user. Do not log instances
   * of `RequestHeaders`.
   */
  readonly authorization: string;
}

/** Options for the upload helper. */
export interface UploadOptions {
  /**
   * Path to the local directory to upload.
   * @remarks Callers are responsible for ensuring this path is within their
   * intended upload tree and does not reference sensitive system directories.
   * The implementation resolves the path to an absolute form and rejects
   * traversal sequences (`..`) that escape the specified root.
   */
  readonly inputDir: string;

  /**
   * Glob patterns to exclude from the upload.
   * Example: ["*.txt", "*.csv"]
   */
  readonly exclude?: string[];

  /**
   * Whether to overwrite objects that already exist in the bucket.
   * Defaults to true. Set to false to resume a partial upload.
   */
  readonly overwrite?: boolean;
}

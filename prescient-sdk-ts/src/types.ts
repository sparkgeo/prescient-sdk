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
  /** Base URL of the Prescient API endpoint. */
  readonly endpointUrl: string;

  /** OAuth2 authentication provider. Defaults to MICROSOFT. */
  readonly authProvider?: AuthProvider;

  /** OAuth2 client ID issued by the selected authentication provider. */
  readonly clientId: string;

  /** OAuth2 token endpoint base URL. */
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
  readonly refreshToken?: string;
  readonly accessToken?: string;
  /** ISO 8601 UTC timestamp at which these credentials expire. */
  readonly expiresAt: string;
}

/**
 * Temporary AWS credentials for S3 access.
 *
 * Use these to construct a native AWS SDK client in the target language.
 * expiresAt is an ISO 8601 UTC timestamp.
 *
 * Python:  boto3.Session(aws_access_key_id=creds.access_key_id, ...)
 * Node.js: new S3Client({ credentials: { accessKeyId: creds.accessKeyId, ... } })
 * Go:      aws.NewCredentialsCache(...)
 * C#:      new SessionAWSCredentials(...)
 */
export interface BucketCredentials {
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
  readonly sessionToken: string;
  /** ISO 8601 UTC timestamp at which these credentials expire. */
  readonly expiresAt: string;
}

/** HTTP request headers used when calling the Prescient API. */
export interface RequestHeaders {
  readonly contentType: string;
  readonly accept: string;
  readonly authorization: string;
}

/** Options for the upload helper. */
export interface UploadOptions {
  /** Path to the local directory to upload. */
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

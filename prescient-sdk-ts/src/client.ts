import * as http from 'http';
import { spawn } from 'child_process';
import { randomBytes } from 'crypto';

import { PublicClientApplication } from '@azure/msal-node';
import { OAuth2Client, CodeChallengeMethod } from 'google-auth-library';
import { STSClient, AssumeRoleWithWebIdentityCommand } from '@aws-sdk/client-sts';
import type { AccountInfo, AuthenticationResult, SilentFlowRequest } from '@azure/msal-node';

import {
  AuthProvider,
  AuthCredentials,
  BucketCredentials,
  RequestHeaders,
  PrescientClientOptions,
} from './types';
import { Settings } from './settings';

const EXPIRATION_SECONDS = 3600;
const MSAL_SCOPES = ['https://graph.microsoft.com/.default'];
const GOOGLE_SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email'];
const OAUTH_TIMEOUT_MS = 5 * 60 * 1000;

/**
 * Client for interacting with the Prescient API.
 *
 * Handles Microsoft MSAL or Google OAuth2 authentication, credential caching,
 * and bucket credential exchange via AWS STS or the Prescient fileproxy endpoint.
 * All credentials are cached using the provider-reported TTL and refreshed
 * transparently on the next call after expiry.
 *
 * @example Microsoft (Entra ID) authentication
 * const client = new PrescientClient({
 *   endpointUrl: 'https://api.prescient.earth',
 *   clientId:    'my-client-id',
 *   authUrl:     'https://login.microsoftonline.com',
 *   tenantId:    'my-tenant-id',
 * });
 * const headers = await client.requestHeaders();
 *
 * @example Google OAuth2 — set PRESCIENT_GOOGLE_CLIENT_SECRET env var before constructing
 * const client = new PrescientClient({
 *   endpointUrl:  'https://api.prescient.earth',
 *   clientId:     'my-client-id',
 *   authUrl:      'https://accounts.google.com',
 *   authProvider: AuthProvider.GOOGLE,
 * });
 */
export class PrescientClient {
  /** STAC catalog URL derived from `endpointUrl`. */
  readonly stacCatalogUrl: string;

  /** Resolved, validated settings driving this client instance. */
  readonly settings: Settings;

  private _authCredentials: AuthCredentials | undefined;
  private _bucketCredentials: BucketCredentials | undefined;
  private _uploadBucketCredentials: BucketCredentials | undefined;

  // In-flight promise deduplication — concurrent callers share one browser
  // flow rather than each opening their own window / fighting for the port.
  private _authInFlight: Promise<AuthCredentials> | undefined;
  private _bucketInFlight: Promise<BucketCredentials> | undefined;
  private _uploadInFlight: Promise<BucketCredentials> | undefined;

  private _msalApp: PublicClientApplication | undefined;
  private _msalAccount: AccountInfo | null | undefined;
  private _googleRefreshToken: string | undefined;
  private _stsClient: STSClient | undefined;

  constructor(opts?: PrescientClientOptions) {
    this.settings = new Settings(opts);
    this.stacCatalogUrl = joinUrl(this.settings.endpointUrl, 'stac');
  }

  /**
   * Fetch (or return cached) authentication credentials.
   *
   * Opens a browser window on first call. Subsequent calls return cached
   * credentials until the provider-reported TTL expires, then silently
   * re-authenticate using the stored refresh token / MSAL account.
   * Concurrent callers share one in-flight auth flow.
   */
  async authenticate(): Promise<AuthCredentials> {
    if (this._authCredentials && !isExpired(this._authCredentials.expiresAt)) {
      return this._authCredentials;
    }
    if (this._authInFlight) return this._authInFlight;
    this._authInFlight = this._doAuthenticate().finally(() => {
      this._authInFlight = undefined;
    });
    return this._authInFlight;
  }

  /** Build `Authorization: Bearer <id_token>` headers for Prescient API requests. */
  async requestHeaders(): Promise<RequestHeaders> {
    const auth = await this.authenticate();
    return {
      contentType: 'application/json',
      accept: 'application/json',
      authorization: `Bearer ${auth.idToken}`,
    };
  }

  /**
   * Fetch (or return cached) temporary S3 credentials for the read bucket.
   *
   * Uses STS `AssumeRoleWithWebIdentity` when `awsRole` is configured;
   * otherwise calls the Prescient `/fileproxy/credentials` endpoint.
   */
  async bucketCredentials(): Promise<BucketCredentials> {
    if (this._bucketCredentials && !isExpired(this._bucketCredentials.expiresAt)) {
      return this._bucketCredentials;
    }
    if (this._bucketInFlight) return this._bucketInFlight;
    this._bucketInFlight = this._doFetchBucketCredentials().finally(() => {
      this._bucketInFlight = undefined;
    });
    return this._bucketInFlight;
  }

  /**
   * Fetch (or return cached) temporary S3 credentials for the upload bucket.
   *
   * Requires `uploadRole` to be set in settings or `PRESCIENT_UPLOAD_ROLE` env var.
   */
  async uploadBucketCredentials(): Promise<BucketCredentials> {
    if (!this.settings.uploadRole) {
      throw new Error(
        'uploadRole is not configured; set PRESCIENT_UPLOAD_ROLE to use the upload bucket.',
      );
    }
    if (this._uploadBucketCredentials && !isExpired(this._uploadBucketCredentials.expiresAt)) {
      return this._uploadBucketCredentials;
    }
    if (this._uploadInFlight) return this._uploadInFlight;
    this._uploadInFlight = this._doFetchUploadCredentials(this.settings.uploadRole).finally(() => {
      this._uploadInFlight = undefined;
    });
    return this._uploadInFlight;
  }

  /** True when no auth credentials have been fetched or the cached credentials have expired. */
  get credentialsExpired(): boolean {
    return !this._authCredentials || isExpired(this._authCredentials.expiresAt);
  }

  /**
   * Refresh all cached credentials.
   *
   * @param force - When true, discards cached credentials and forces a full re-authentication.
   */
  async refreshCredentials(force?: boolean): Promise<void> {
    if (force) {
      this._authCredentials = undefined;
      this._bucketCredentials = undefined;
      this._uploadBucketCredentials = undefined;
    }
    await this.bucketCredentials();
    if (this.settings.uploadRole) {
      await this.uploadBucketCredentials();
    }
  }

  private async _doAuthenticate(): Promise<AuthCredentials> {
    const creds =
      this.settings.authProvider === AuthProvider.GOOGLE
        ? await this._fetchGoogleCredentials()
        : await this._fetchMicrosoftCredentials();
    this._authCredentials = creds;
    return creds;
  }

  private async _doFetchBucketCredentials(): Promise<BucketCredentials> {
    const creds = this.settings.awsRole
      ? await this._fetchStsCredentials(this.settings.awsRole)
      : await this._fetchFileproxyCredentials();
    this._bucketCredentials = creds;
    return creds;
  }

  private async _doFetchUploadCredentials(role: string): Promise<BucketCredentials> {
    const creds = await this._fetchStsCredentials(role);
    this._uploadBucketCredentials = creds;
    return creds;
  }

  private _getMsalApp(): PublicClientApplication {
    if (!this._msalApp) {
      const authority = joinUrl(this.settings.authUrl, this.settings.tenantId!);
      this._msalApp = new PublicClientApplication({
        auth: { clientId: this.settings.clientId, authority },
        system: {
          loggerOptions: { loggerCallback: () => {}, piiLoggingEnabled: false },
        },
      });
    }
    return this._msalApp;
  }

  private _getStsClient(): STSClient {
    if (!this._stsClient) {
      this._stsClient = new STSClient({ region: this.settings.awsRegion });
    }
    return this._stsClient;
  }

  private async _fetchMicrosoftCredentials(): Promise<AuthCredentials> {
    const app = this._getMsalApp();
    let result: AuthenticationResult | null = null;

    if (this._msalAccount != null) {
      const req: SilentFlowRequest = { scopes: MSAL_SCOPES, account: this._msalAccount };
      try {
        result = await app.acquireTokenSilent(req);
      } catch {
        result = null;
      }
    }

    if (!result) {
      result = await app.acquireTokenInteractive({
        scopes: MSAL_SCOPES,
        openBrowser: openSystemBrowser,
        successTemplate: '<h1>Sign-in successful</h1><p>You may close this window.</p>',
        errorTemplate: '<h1>Sign-in failed</h1><p>{errorDetails}</p>',
      });
    }

    if (!result.idToken) {
      throw new Error('Failed to obtain id_token from Microsoft MSAL.');
    }

    this._msalAccount = result.account;

    return {
      idToken: result.idToken,
      accessToken: result.accessToken,
      expiresAt: (result.expiresOn ?? new Date(Date.now() + EXPIRATION_SECONDS * 1000)).toISOString(),
    };
  }

  private async _fetchGoogleCredentials(): Promise<AuthCredentials> {
    const redirectUri = `http://localhost:${this.settings.googleRedirectPort}`;
    const oauth2Client = new OAuth2Client(
      this.settings.clientId,
      this.settings._googleClientSecret!,
      redirectUri,
    );

    let idToken: string;
    let refreshToken: string | undefined;
    let accessToken: string | undefined;
    let expiresAt: string;

    if (this._googleRefreshToken) {
      oauth2Client.setCredentials({ refresh_token: this._googleRefreshToken });
      const { credentials } = await oauth2Client.refreshAccessToken();
      idToken = assertIdToken(credentials.id_token, 'refresh');
      refreshToken = credentials.refresh_token ?? this._googleRefreshToken;
      accessToken = credentials.access_token ?? undefined;
      expiresAt = credentials.expiry_date
        ? new Date(credentials.expiry_date).toISOString()
        : new Date(Date.now() + EXPIRATION_SECONDS * 1000).toISOString();
    } else {
      // PKCE (RFC 8252 §8.1) — prevents authorization code interception
      const pkce = await oauth2Client.generateCodeVerifierAsync();
      if (!pkce.codeChallenge) {
        throw new Error('Failed to generate PKCE code challenge.');
      }
      // Random state — prevents CSRF (RFC 6749 §10.12)
      const state = randomBytes(16).toString('hex');

      const authUrl = oauth2Client.generateAuthUrl({
        access_type: 'offline',
        scope: GOOGLE_SCOPES,
        prompt: 'consent',
        code_challenge: pkce.codeChallenge,
        code_challenge_method: CodeChallengeMethod.S256,
        state,
      });

      const code = await captureOAuthCode(this.settings.googleRedirectPort, authUrl, state);
      const { tokens } = await oauth2Client.getToken({ code, codeVerifier: pkce.codeVerifier });
      idToken = assertIdToken(tokens.id_token, 'interactive');
      refreshToken = tokens.refresh_token ?? undefined;
      accessToken = tokens.access_token ?? undefined;
      expiresAt = tokens.expiry_date
        ? new Date(tokens.expiry_date).toISOString()
        : new Date(Date.now() + EXPIRATION_SECONDS * 1000).toISOString();
    }

    if (refreshToken) {
      this._googleRefreshToken = refreshToken;
    }

    return { idToken, refreshToken, accessToken, expiresAt };
  }

  private async _fetchStsCredentials(role: string): Promise<BucketCredentials> {
    const auth = await this.authenticate();

    // Sanitise and truncate to stay within the AWS 64-char RoleSessionName limit.
    // Use the last path component (handles arn:…:role/path/to/Name → Name).
    const stub = (role.split('/').at(-1) ?? role.slice(-10))
      .replace(/[^a-zA-Z0-9+=,.@_-]/g, '-')
      .slice(0, 44); // prefix 'prescient-s3-access-' is 20 chars → 20+44=64
    const roleSessionName = `prescient-s3-access-${stub}`;

    const response = await this._getStsClient().send(
      new AssumeRoleWithWebIdentityCommand({
        DurationSeconds: EXPIRATION_SECONDS,
        RoleArn: role,
        RoleSessionName: roleSessionName,
        WebIdentityToken: auth.idToken,
      }),
    );

    const creds = response.Credentials;
    if (!creds?.AccessKeyId || !creds?.SecretAccessKey || !creds?.SessionToken) {
      throw new Error('Failed to obtain AWS credentials from STS: missing fields in response.');
    }

    return {
      accessKeyId: creds.AccessKeyId,
      secretAccessKey: creds.SecretAccessKey,
      sessionToken: creds.SessionToken,
      expiresAt: (creds.Expiration ?? new Date(Date.now() + EXPIRATION_SECONDS * 1000)).toISOString(),
    };
  }

  private async _fetchFileproxyCredentials(): Promise<BucketCredentials> {
    const hdrs = await this.requestHeaders();
    const url = joinUrl(this.settings.endpointUrl, 'fileproxy/credentials');

    const response = await fetch(url, {
      headers: {
        'Content-Type': hdrs.contentType,
        Accept: hdrs.accept,
        Authorization: hdrs.authorization,
      },
    });

    if (!response.ok) {
      throw new Error(
        `Fileproxy credentials request failed: ${response.status} ${response.statusText}`,
      );
    }

    const payload = (await response.json()) as {
      readonly access_key_id: string;
      readonly secret_access_key: string;
      readonly session_token: string;
      readonly expiration: string;
    };

    const expiry = new Date(payload.expiration);
    if (isNaN(expiry.getTime())) {
      throw new Error(
        `fileproxy returned an invalid expiration timestamp: "${payload.expiration}"`,
      );
    }

    return {
      accessKeyId: payload.access_key_id,
      secretAccessKey: payload.secret_access_key,
      sessionToken: payload.session_token,
      expiresAt: expiry.toISOString(),
    };
  }
}

// ─── module-level helpers (not exported, not visible to jsii) ────────────────

function joinUrl(base: string, path: string): string {
  const b = base.endsWith('/') ? base : `${base}/`;
  return new URL(path, b).href;
}

function isExpired(expiresAt: string): boolean {
  return new Date(expiresAt).getTime() <= Date.now();
}

function assertIdToken(val: string | null | undefined, flow: string): string {
  if (typeof val !== 'string' || val === '') {
    throw new Error(`Failed to obtain id_token from Google OAuth2 (${flow} flow).`);
  }
  return val;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function openSystemBrowser(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const isWin = process.platform === 'win32';
    const cmd = process.platform === 'darwin' ? 'open' : isWin ? 'cmd' : 'xdg-open';
    const args = isWin ? ['/c', 'start', '', url] : [url];
    const proc = spawn(cmd, args, { detached: true, stdio: 'ignore' });
    proc.on('error', reject);
    // 'spawn' fires only after the process successfully launched
    proc.on('spawn', () => {
      proc.unref();
      resolve();
    });
  });
}

function captureOAuthCode(port: number, authUrl: string, expectedState: string): Promise<string> {
  return new Promise((resolve, reject) => {
    let settled = false;

    function settle(fn: () => void): void {
      if (!settled) {
        settled = true;
        fn();
      }
    }

    const server = http.createServer((req, res) => {
      try {
        // Only accept GET requests to '/'
        if (req.method !== 'GET') {
          res.writeHead(405).end();
          return;
        }
        const reqUrl = new URL(req.url ?? '/', `http://127.0.0.1:${port}`);
        if (reqUrl.pathname !== '/') {
          res.writeHead(404).end();
          return;
        }

        // Validate state to prevent CSRF / authorization-code injection
        const returnedState = reqUrl.searchParams.get('state');
        if (returnedState !== expectedState) {
          res.writeHead(400, { 'Content-Type': 'text/plain' });
          res.end('OAuth2 error: invalid state parameter.');
          server.close(() =>
            settle(() =>
              reject(new Error('OAuth2 error: invalid or missing state parameter.')),
            ),
          );
          return;
        }

        const code = reqUrl.searchParams.get('code');
        const error = reqUrl.searchParams.get('error');
        if (code) {
          res.writeHead(200, { 'Content-Type': 'text/html' });
          res.end('<h1>Authentication successful</h1><p>You may close this window.</p>');
          server.close(() => settle(() => resolve(code)));
        } else {
          res.writeHead(400, { 'Content-Type': 'text/html' });
          res.end(
            `<h1>Authentication failed</h1><p>${escapeHtml(String(error ?? 'no code in redirect'))}</p>`,
          );
          server.close(() =>
            settle(() => reject(new Error(`OAuth2 error: ${error ?? 'no code in redirect'}`))),
          );
        }
      } catch (e) {
        server.close(() => settle(() => reject(e)));
      }
    });

    const timeout = setTimeout(() => {
      server.close(() =>
        settle(() =>
          reject(new Error('OAuth2 browser authentication timed out after 5 minutes.')),
        ),
      );
    }, OAUTH_TIMEOUT_MS);

    server.on('error', (err) => settle(() => reject(err)));
    server.on('close', () => clearTimeout(timeout));

    // Bind to loopback only — redirect URI is http://localhost:<port> which
    // resolves to 127.0.0.1; binding to all interfaces during the auth window
    // would expose the code-capture endpoint to the local network.
    server.listen(port, '127.0.0.1', () => {
      openSystemBrowser(authUrl).catch((err) => settle(() => reject(err)));
    });
  });
}

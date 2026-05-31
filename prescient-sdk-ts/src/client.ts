import * as http from 'http';
import { spawn } from 'child_process';

import { PublicClientApplication } from '@azure/msal-node';
import { OAuth2Client } from 'google-auth-library';
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
 * All credentials are cached for a 1-hour TTL and refreshed transparently on
 * the next call after expiry.
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

  /** @internal */
  private _msalApp: PublicClientApplication | undefined;
  /** @internal */
  private _msalAccount: AccountInfo | null | undefined;
  /** @internal */
  private _googleRefreshToken: string | undefined;

  constructor(opts?: PrescientClientOptions) {
    this.settings = new Settings(opts);
    this.stacCatalogUrl = joinUrl(this.settings.endpointUrl, 'stac');
  }

  /**
   * Fetch (or return cached) authentication credentials.
   *
   * Opens a browser window on first call. Subsequent calls return cached
   * credentials until the 1-hour TTL expires, then silently re-authenticate
   * using the stored refresh token / MSAL account.
   */
  async authenticate(): Promise<AuthCredentials> {
    if (this._authCredentials && !isExpired(this._authCredentials.expiresAt)) {
      return this._authCredentials;
    }

    const raw =
      this.settings.authProvider === AuthProvider.GOOGLE
        ? await this._fetchGoogleCredentials()
        : await this._fetchMicrosoftCredentials();

    this._authCredentials = {
      ...raw,
      expiresAt: new Date(Date.now() + EXPIRATION_SECONDS * 1000).toISOString(),
    };

    return this._authCredentials;
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
    this._bucketCredentials = this.settings.awsRole
      ? await this._fetchStsCredentials(this.settings.awsRole)
      : await this._fetchFileproxyCredentials();
    return this._bucketCredentials;
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
    this._uploadBucketCredentials = await this._fetchStsCredentials(this.settings.uploadRole);
    return this._uploadBucketCredentials;
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
      const authUrl = oauth2Client.generateAuthUrl({
        access_type: 'offline',
        scope: GOOGLE_SCOPES,
        prompt: 'consent',
      });
      const code = await captureOAuthCode(this.settings.googleRedirectPort, authUrl);
      const { tokens } = await oauth2Client.getToken(code);
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
    const stsClient = new STSClient({ region: this.settings.awsRegion });

    const parts = role.split('/');
    const stub = parts.length > 1 ? parts[1] : role.slice(-10);
    const roleSessionName = `prescient-s3-access-${stub}`;

    const response = await stsClient.send(
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

    return {
      accessKeyId: payload.access_key_id,
      secretAccessKey: payload.secret_access_key,
      sessionToken: payload.session_token,
      expiresAt: payload.expiration,
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

function openSystemBrowser(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const isWin = process.platform === 'win32';
    const cmd = process.platform === 'darwin' ? 'open' : isWin ? 'cmd' : 'xdg-open';
    const args = isWin ? ['/c', 'start', '', url] : [url];
    const proc = spawn(cmd, args, { detached: true, stdio: 'ignore' });
    proc.unref();
    proc.on('error', reject);
    resolve();
  });
}

function captureOAuthCode(port: number, authUrl: string): Promise<string> {
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
        const reqUrl = new URL(req.url ?? '/', `http://localhost:${port}`);
        const code = reqUrl.searchParams.get('code');
        const error = reqUrl.searchParams.get('error');
        if (code) {
          res.writeHead(200, { 'Content-Type': 'text/html' });
          res.end('<h1>Authentication successful</h1><p>You may close this window.</p>');
          server.close(() => settle(() => resolve(code)));
        } else {
          res.writeHead(400, { 'Content-Type': 'text/html' });
          res.end(`<h1>Authentication failed</h1><p>${String(error ?? 'no code in redirect')}</p>`);
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

    server.listen(port, () => {
      openSystemBrowser(authUrl).catch((err) => settle(() => reject(err)));
    });
  });
}

import {
  AuthProvider,
  PrescientClientOptions,
  AuthCredentials,
  BucketCredentials,
  RequestHeaders,
  UploadOptions,
} from '../types';

describe('AuthProvider enum', () => {
  it('has MICROSOFT and GOOGLE values', () => {
    expect(AuthProvider.MICROSOFT).toBe('microsoft');
    expect(AuthProvider.GOOGLE).toBe('google');
  });
});

describe('PrescientClientOptions', () => {
  it('accepts required fields only', () => {
    const opts: PrescientClientOptions = {
      endpointUrl: 'https://api.example.com',
      clientId: 'client-id',
      authUrl: 'https://auth.example.com',
    };
    expect(opts.endpointUrl).toBe('https://api.example.com');
    expect(opts.authProvider).toBeUndefined();
    expect(opts.tenantId).toBeUndefined();
  });

  it('accepts microsoft provider with tenantId', () => {
    const opts: PrescientClientOptions = {
      endpointUrl: 'https://api.example.com',
      clientId: 'client-id',
      authUrl: 'https://login.microsoftonline.com',
      authProvider: AuthProvider.MICROSOFT,
      tenantId: 'tenant-id',
    };
    expect(opts.authProvider).toBe('microsoft');
    expect(opts.tenantId).toBe('tenant-id');
  });

  it('accepts google provider without client secret field', () => {
    const opts: PrescientClientOptions = {
      endpointUrl: 'https://api.example.com',
      clientId: 'client-id',
      authUrl: 'https://accounts.google.com',
      authProvider: AuthProvider.GOOGLE,
      googleRedirectPort: 8765,
    };
    expect(opts.authProvider).toBe('google');
    // googleClientSecret intentionally absent from struct
    expect((opts as unknown as Record<string, unknown>)['googleClientSecret']).toBeUndefined();
  });
});

describe('AuthCredentials', () => {
  it('accepts required idToken and ISO 8601 expiresAt', () => {
    const creds: AuthCredentials = {
      idToken: 'id-token',
      expiresAt: '2024-01-01T00:00:00Z',
    };
    expect(creds.idToken).toBe('id-token');
    expect(creds.refreshToken).toBeUndefined();
  });
});

describe('BucketCredentials', () => {
  it('holds AWS temp credential fields', () => {
    const creds: BucketCredentials = {
      accessKeyId: 'AKIA...',
      secretAccessKey: 'secret',
      sessionToken: 'token',
      expiresAt: '2024-01-01T01:00:00Z',
    };
    expect(creds.accessKeyId).toMatch(/^AKIA/);
    expect(creds.expiresAt).toBe('2024-01-01T01:00:00Z');
  });
});

describe('RequestHeaders', () => {
  it('holds content type, accept, authorization', () => {
    const headers: RequestHeaders = {
      contentType: 'application/json',
      accept: 'application/json',
      authorization: 'Bearer token',
    };
    expect(headers.authorization).toMatch(/^Bearer /);
  });
});

describe('UploadOptions', () => {
  it('accepts inputDir only', () => {
    const opts: UploadOptions = { inputDir: '/data' };
    expect(opts.overwrite).toBeUndefined();
    expect(opts.exclude).toBeUndefined();
  });

  it('accepts full options', () => {
    const opts: UploadOptions = {
      inputDir: '/data',
      exclude: ['*.tmp', '*.log'],
      overwrite: false,
    };
    expect(opts.exclude).toHaveLength(2);
    expect(opts.overwrite).toBe(false);
  });
});

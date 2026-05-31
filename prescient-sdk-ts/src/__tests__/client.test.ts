import { PrescientClient } from '../client';
import { AuthProvider } from '../types';

const MICROSOFT_OPTS = {
  endpointUrl: 'https://api.example.com',
  clientId: 'client-id',
  authUrl: 'https://login.microsoftonline.com',
  tenantId: 'tenant-id',
};

describe('PrescientClient — constructor', () => {
  it('constructs with microsoft opts', () => {
    const client = new PrescientClient(MICROSOFT_OPTS);
    expect(client.settings.endpointUrl).toBe('https://api.example.com');
    expect(client.settings.authProvider).toBe(AuthProvider.MICROSOFT);
    expect(client.settings.tenantId).toBe('tenant-id');
  });

  it('derives stacCatalogUrl from endpointUrl', () => {
    const client = new PrescientClient(MICROSOFT_OPTS);
    expect(client.stacCatalogUrl).toBe('https://api.example.com/stac');
  });

  it('derives stacCatalogUrl when endpointUrl has trailing slash', () => {
    const client = new PrescientClient({ ...MICROSOFT_OPTS, endpointUrl: 'https://api.example.com/' });
    expect(client.stacCatalogUrl).toBe('https://api.example.com/stac');
  });

  it('derives stacCatalogUrl when endpointUrl has base path', () => {
    const client = new PrescientClient({ ...MICROSOFT_OPTS, endpointUrl: 'https://api.example.com/v1/' });
    expect(client.stacCatalogUrl).toBe('https://api.example.com/v1/stac');
  });

  it('throws on http:// endpointUrl', () => {
    expect(() =>
      new PrescientClient({ ...MICROSOFT_OPTS, endpointUrl: 'http://api.example.com' }),
    ).toThrow('endpointUrl must be an HTTPS URL');
  });

  it('throws on SSRF endpointUrl (IMDS)', () => {
    expect(() =>
      new PrescientClient({ ...MICROSOFT_OPTS, endpointUrl: 'https://169.254.169.254/latest' }),
    ).toThrow('must not target internal infrastructure');
  });

  it('throws when microsoft provider missing tenantId', () => {
    expect(() =>
      new PrescientClient({
        endpointUrl: 'https://api.example.com',
        clientId: 'client-id',
        authUrl: 'https://login.microsoftonline.com',
        authProvider: AuthProvider.MICROSOFT,
      }),
    ).toThrow('tenantId is required when authProvider is MICROSOFT');
  });
});

describe('PrescientClient — credentialsExpired', () => {
  it('is true before any authentication', () => {
    const client = new PrescientClient(MICROSOFT_OPTS);
    expect(client.credentialsExpired).toBe(true);
  });
});

describe('PrescientClient — uploadBucketCredentials', () => {
  it('rejects when uploadRole not configured', async () => {
    const client = new PrescientClient(MICROSOFT_OPTS);
    await expect(client.uploadBucketCredentials()).rejects.toThrow(
      'uploadRole is not configured',
    );
  });
});

describe('PrescientClient — settings passthrough', () => {
  it('exposes resolved settings', () => {
    const client = new PrescientClient({ ...MICROSOFT_OPTS, awsRegion: 'us-east-1' });
    expect(client.settings.awsRegion).toBe('us-east-1');
  });

  it('defaults googleRedirectPort to 8765', () => {
    const client = new PrescientClient(MICROSOFT_OPTS);
    expect(client.settings.googleRedirectPort).toBe(8765);
  });
});

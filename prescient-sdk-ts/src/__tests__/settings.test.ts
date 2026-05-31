import { Settings } from '../settings';
import { AuthProvider } from '../types';

const BASE = {
  endpointUrl: 'https://api.example.com',
  clientId: 'client-id',
  authUrl: 'https://auth.example.com',
};

const MICROSOFT_OPTS = { ...BASE, tenantId: 'tenant-id' };
const GOOGLE_ENV = {
  PRESCIENT_ENDPOINT_URL: 'https://api.example.com',
  PRESCIENT_CLIENT_ID: 'client-id',
  PRESCIENT_AUTH_URL: 'https://auth.example.com',
  PRESCIENT_AUTH_PROVIDER: 'google',
  PRESCIENT_GOOGLE_CLIENT_SECRET: 'google-secret', // gitleaks:allow
};

function withEnv(vars: Record<string, string>, fn: () => void): void {
  const saved: Record<string, string | undefined> = {};
  for (const k of Object.keys(vars)) {
    saved[k] = process.env[k];
    process.env[k] = vars[k];
  }
  try {
    fn();
  } finally {
    for (const k of Object.keys(vars)) {
      if (saved[k] === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = saved[k];
      }
    }
  }
}

describe('Settings — from options', () => {
  it('constructs with microsoft provider and tenantId', () => {
    const s = new Settings(MICROSOFT_OPTS);
    expect(s.endpointUrl).toBe('https://api.example.com');
    expect(s.authProvider).toBe(AuthProvider.MICROSOFT);
    expect(s.tenantId).toBe('tenant-id');
    expect(s.googleRedirectPort).toBe(8765);
  });

  it('constructs with google provider (secret from env)', () => {
    withEnv({ PRESCIENT_GOOGLE_CLIENT_SECRET: 'secret' }, () => {
      const s = new Settings({ ...BASE, authProvider: AuthProvider.GOOGLE });
      expect(s.authProvider).toBe(AuthProvider.GOOGLE);
      expect(s._googleClientSecret).toBe('secret');
    });
  });

  it('defaults authProvider to MICROSOFT', () => {
    const s = new Settings(MICROSOFT_OPTS);
    expect(s.authProvider).toBe(AuthProvider.MICROSOFT);
  });

  it('uses provided googleRedirectPort', () => {
    withEnv({ PRESCIENT_GOOGLE_CLIENT_SECRET: 'secret' }, () => {
      const s = new Settings({ ...BASE, authProvider: AuthProvider.GOOGLE, googleRedirectPort: 9000 });
      expect(s.googleRedirectPort).toBe(9000);
    });
  });
});

describe('Settings — from environment variables', () => {
  it('reads all PRESCIENT_* env vars', () => {
    withEnv(GOOGLE_ENV, () => {
      const s = new Settings();
      expect(s.endpointUrl).toBe('https://api.example.com');
      expect(s.authProvider).toBe(AuthProvider.GOOGLE);
      expect(s._googleClientSecret).toBe('google-secret');
    });
  });

  it('env var overrides default redirect port', () => {
    withEnv({ ...GOOGLE_ENV, PRESCIENT_GOOGLE_REDIRECT_PORT: '4321' }, () => {
      const s = new Settings();
      expect(s.googleRedirectPort).toBe(4321);
    });
  });

  it('parses PRESCIENT_AUTH_PROVIDER case-insensitively', () => {
    withEnv({ ...GOOGLE_ENV, PRESCIENT_AUTH_PROVIDER: 'GOOGLE' }, () => {
      const s = new Settings();
      expect(s.authProvider).toBe(AuthProvider.GOOGLE);
    });
  });
});

describe('Settings — validation errors', () => {
  it('throws if endpointUrl missing', () => {
    expect(() => new Settings({ ...BASE, endpointUrl: '' } as any)).toThrow(
      'endpointUrl is required',
    );
  });

  it('throws if endpointUrl is http://', () => {
    expect(() =>
      new Settings({ ...MICROSOFT_OPTS, endpointUrl: 'http://api.example.com' }),
    ).toThrow('endpointUrl must be an HTTPS URL');
  });

  it('throws if authUrl is http://', () => {
    expect(() =>
      new Settings({ ...MICROSOFT_OPTS, authUrl: 'http://auth.example.com' }),
    ).toThrow('authUrl must be an HTTPS URL');
  });

  it('throws if clientId missing', () => {
    expect(() => new Settings({ ...BASE, clientId: '', tenantId: 'tid' })).toThrow(
      'clientId is required',
    );
  });

  it('throws if microsoft provider missing tenantId', () => {
    expect(() => new Settings({ ...BASE, authProvider: AuthProvider.MICROSOFT })).toThrow(
      'tenantId is required when authProvider is MICROSOFT',
    );
  });

  it('throws if google provider missing PRESCIENT_GOOGLE_CLIENT_SECRET', () => {
    expect(() =>
      new Settings({ ...BASE, authProvider: AuthProvider.GOOGLE }),
    ).toThrow('PRESCIENT_GOOGLE_CLIENT_SECRET env var is required');
  });

  it('throws on invalid PRESCIENT_AUTH_PROVIDER env value', () => {
    withEnv(
      {
        ...GOOGLE_ENV,
        PRESCIENT_AUTH_PROVIDER: 'facebook',
        PRESCIENT_GOOGLE_CLIENT_SECRET: 'secret',
      },
      () => {
        expect(() => new Settings()).toThrow('Invalid PRESCIENT_AUTH_PROVIDER value "facebook"');
      },
    );
  });

  it('throws on invalid PRESCIENT_GOOGLE_REDIRECT_PORT', () => {
    withEnv({ ...GOOGLE_ENV, PRESCIENT_GOOGLE_REDIRECT_PORT: 'abc' }, () => {
      expect(() => new Settings()).toThrow('Invalid PRESCIENT_GOOGLE_REDIRECT_PORT value "abc"');
    });
  });

  it('throws on out-of-range PRESCIENT_GOOGLE_REDIRECT_PORT', () => {
    withEnv({ ...GOOGLE_ENV, PRESCIENT_GOOGLE_REDIRECT_PORT: '99999' }, () => {
      expect(() => new Settings()).toThrow('Invalid PRESCIENT_GOOGLE_REDIRECT_PORT value "99999"');
    });
  });
});

describe('Settings — port boundary validation', () => {
  it('throws on out-of-range googleRedirectPort option (0)', () => {
    withEnv({ PRESCIENT_GOOGLE_CLIENT_SECRET: 'secret' }, () => { // gitleaks:allow
      expect(() =>
        new Settings({ ...BASE, authProvider: AuthProvider.GOOGLE, googleRedirectPort: 0 }),
      ).toThrow('googleRedirectPort must be an integer 1–65535');
    });
  });

  it('throws on out-of-range googleRedirectPort option (65536)', () => {
    withEnv({ PRESCIENT_GOOGLE_CLIENT_SECRET: 'secret' }, () => { // gitleaks:allow
      expect(() =>
        new Settings({ ...BASE, authProvider: AuthProvider.GOOGLE, googleRedirectPort: 65536 }),
      ).toThrow('googleRedirectPort must be an integer 1–65535');
    });
  });

  it('throws on non-integer googleRedirectPort option (1.5)', () => {
    withEnv({ PRESCIENT_GOOGLE_CLIENT_SECRET: 'secret' }, () => { // gitleaks:allow
      expect(() =>
        new Settings({ ...BASE, authProvider: AuthProvider.GOOGLE, googleRedirectPort: 1.5 }),
      ).toThrow('googleRedirectPort must be an integer 1–65535');
    });
  });

  it('throws on scientific-notation PRESCIENT_GOOGLE_REDIRECT_PORT', () => {
    withEnv({ ...GOOGLE_ENV, PRESCIENT_GOOGLE_REDIRECT_PORT: '1e4' }, () => {
      expect(() => new Settings()).toThrow('Invalid PRESCIENT_GOOGLE_REDIRECT_PORT value "1e4"');
    });
  });
});

describe('Settings — SSRF prevention', () => {
  it('throws if endpointUrl targets IMDS (169.254.169.254)', () => {
    expect(() =>
      new Settings({ ...MICROSOFT_OPTS, endpointUrl: 'https://169.254.169.254/latest' }),
    ).toThrow('must not target internal infrastructure');
  });

  it('throws if endpointUrl targets localhost', () => {
    expect(() =>
      new Settings({ ...MICROSOFT_OPTS, endpointUrl: 'https://localhost:8080' }),
    ).toThrow('must not target internal infrastructure');
  });

  it('throws if endpointUrl targets RFC 1918 (192.168.x.x)', () => {
    expect(() =>
      new Settings({ ...MICROSOFT_OPTS, endpointUrl: 'https://192.168.1.1' }),
    ).toThrow('must not target internal infrastructure');
  });

  it('throws if authUrl targets RFC 1918 (10.x.x.x)', () => {
    expect(() =>
      new Settings({ ...MICROSOFT_OPTS, authUrl: 'https://10.0.0.1/token' }),
    ).toThrow('must not target internal infrastructure');
  });
});

describe('Settings — toJSON', () => {
  it('excludes _googleClientSecret from JSON.stringify', () => {
    withEnv({ PRESCIENT_GOOGLE_CLIENT_SECRET: 'secret' }, () => { // gitleaks:allow
      const s = new Settings({ ...BASE, authProvider: AuthProvider.GOOGLE });
      const json = JSON.parse(JSON.stringify(s)) as Record<string, unknown>;
      expect(json['_googleClientSecret']).toBeUndefined();
      expect(json['endpointUrl']).toBe('https://api.example.com');
    });
  });
});

describe('Settings — awsRole validation', () => {
  it('accepts a valid ARN', () => {
    const s = new Settings({ ...MICROSOFT_OPTS, awsRole: 'arn:aws:iam::123456789012:role/MyRole' });
    expect(s.awsRole).toBe('arn:aws:iam::123456789012:role/MyRole');
  });

  it('throws on invalid awsRole (missing arn: prefix)', () => {
    expect(() =>
      new Settings({ ...MICROSOFT_OPTS, awsRole: 'not-an-arn' }),
    ).toThrow('awsRole must be a valid AWS ARN');
  });
});

describe('Settings — opts take precedence over env', () => {
  it('opts.endpointUrl wins over PRESCIENT_ENDPOINT_URL', () => {
    withEnv(
      { ...GOOGLE_ENV, PRESCIENT_ENDPOINT_URL: 'https://env.example.com' },
      () => {
        const s = new Settings({ ...BASE, authProvider: AuthProvider.GOOGLE });
        expect(s.endpointUrl).toBe('https://api.example.com');
      },
    );
  });
});

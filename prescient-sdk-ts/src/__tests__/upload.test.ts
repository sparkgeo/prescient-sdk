import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

import { mockClient } from 'aws-sdk-client-mock';
import { HeadObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { Upload } from '@aws-sdk/lib-storage';

import { Uploader } from '../upload';
import { PrescientClient } from '../client';

// Module-level mock — hoisted before imports, controls all Upload instances.
jest.mock('@aws-sdk/lib-storage', () => ({
  Upload: jest.fn().mockImplementation(() => ({
    done: jest.fn().mockResolvedValue({}),
  })),
}));

// fs.ReadStream opens the file handle eagerly. Since Upload is mocked and never
// consumes the stream, the open races with afterEach cleanup → ENOENT crash.
// Spy once at module level so the same mock is active for all tests.
jest.spyOn(fs, 'createReadStream').mockReturnValue({
  destroy: jest.fn(),
  on: jest.fn().mockReturnThis(),
} as unknown as fs.ReadStream);

const s3Mock = mockClient(S3Client);

const CLIENT_OPTS = {
  endpointUrl: 'https://api.example.com',
  clientId: 'client-id',
  authUrl: 'https://login.microsoftonline.com',
  tenantId: 'tenant-id',
  uploadBucket: 'test-bucket',
  uploadRole: 'arn:aws:iam::123456789012:role/upload-role',
  awsRegion: 'us-east-1',
};

const MOCK_CREDS = {
  accessKeyId: 'AKIAIOSFODNN7EXAMPLE',
  secretAccessKey: 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
  sessionToken: 'AQoXnyc4lcK4w',
  expiresAt: new Date(Date.now() + 3600 * 1000).toISOString(),
};

function makeTmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'prescient-upload-test-'));
}

function touch(base: string, ...parts: string[]): string {
  const p = path.join(base, ...parts);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, 'data');
  return p;
}

describe('Uploader.upload', () => {
  let tmpDir: string;
  let client: PrescientClient;
  const MockUpload = Upload as jest.MockedClass<typeof Upload>;

  beforeEach(() => {
    tmpDir = makeTmp();
    s3Mock.reset();
    jest.clearAllMocks();
    client = new PrescientClient(CLIENT_OPTS);
    jest.spyOn(client, 'uploadBucketCredentials').mockResolvedValue(MOCK_CREDS);
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('uploads a single file', async () => {
    touch(tmpDir, 'file.txt');
    await Uploader.upload({ inputDir: tmpDir }, client);
    expect(MockUpload).toHaveBeenCalledTimes(1);
    const { params } = MockUpload.mock.calls[0][0];
    expect(params.Bucket).toBe('test-bucket');
    expect(params.Key).toBe(`${path.basename(tmpDir)}/file.txt`);
  });

  it('uploads file in nested subdirectory with full relative key', async () => {
    touch(tmpDir, 'sub', 'nested.txt');
    await Uploader.upload({ inputDir: tmpDir }, client);
    const { params } = MockUpload.mock.calls[0][0];
    expect(params.Key).toBe(`${path.basename(tmpDir)}/sub/nested.txt`);
  });

  it('uploads multiple files', async () => {
    touch(tmpDir, 'a.txt');
    touch(tmpDir, 'b.txt');
    await Uploader.upload({ inputDir: tmpDir }, client);
    expect(MockUpload).toHaveBeenCalledTimes(2);
  });

  it('uploads nothing for an empty directory', async () => {
    await Uploader.upload({ inputDir: tmpDir }, client);
    expect(MockUpload).not.toHaveBeenCalled();
  });

  it('excludes files matching basename glob pattern', async () => {
    touch(tmpDir, 'keep.csv');
    touch(tmpDir, 'skip.txt');
    await Uploader.upload({ inputDir: tmpDir, exclude: ['*.txt'] }, client);
    expect(MockUpload).toHaveBeenCalledTimes(1);
    const { params } = MockUpload.mock.calls[0][0];
    expect(params.Key).toContain('keep.csv');
  });

  it('excludes files in subdirectory matching path pattern', async () => {
    touch(tmpDir, 'keep.txt');
    touch(tmpDir, 'logs', 'debug.log');
    await Uploader.upload({ inputDir: tmpDir, exclude: ['logs/*'] }, client);
    expect(MockUpload).toHaveBeenCalledTimes(1);
    const { params } = MockUpload.mock.calls[0][0];
    expect(params.Key).toContain('keep.txt');
  });

  it('excludes files matching ** glob across multiple subdirectory levels', async () => {
    touch(tmpDir, 'keep.csv');
    touch(tmpDir, 'a', 'debug.log');
    touch(tmpDir, 'a', 'b', 'deep.log');
    await Uploader.upload({ inputDir: tmpDir, exclude: ['**/*.log'] }, client);
    expect(MockUpload).toHaveBeenCalledTimes(1);
    const { params } = MockUpload.mock.calls[0][0];
    expect(params.Key).toContain('keep.csv');
  });

  it('excludes all files when pattern is *', async () => {
    touch(tmpDir, 'a.txt');
    touch(tmpDir, 'b.csv');
    await Uploader.upload({ inputDir: tmpDir, exclude: ['*'] }, client);
    expect(MockUpload).not.toHaveBeenCalled();
  });

  it('skips existing objects when overwrite is false', async () => {
    touch(tmpDir, 'exists.txt');
    s3Mock.on(HeadObjectCommand).resolves({});
    await Uploader.upload({ inputDir: tmpDir, overwrite: false }, client);
    expect(MockUpload).not.toHaveBeenCalled();
  });

  it('uploads when overwrite is false and object is absent (404)', async () => {
    touch(tmpDir, 'new.txt');
    s3Mock
      .on(HeadObjectCommand)
      .rejects({ name: 'NotFound', $metadata: { httpStatusCode: 404 } });
    await Uploader.upload({ inputDir: tmpDir, overwrite: false }, client);
    expect(MockUpload).toHaveBeenCalledTimes(1);
  });

  it('uploads when overwrite is false and object is absent (NoSuchKey)', async () => {
    touch(tmpDir, 'new.txt');
    s3Mock
      .on(HeadObjectCommand)
      .rejects({ name: 'NoSuchKey', $metadata: { httpStatusCode: 404 } });
    await Uploader.upload({ inputDir: tmpDir, overwrite: false }, client);
    expect(MockUpload).toHaveBeenCalledTimes(1);
  });

  it('propagates non-404 HeadObject errors when overwrite is false', async () => {
    touch(tmpDir, 'file.txt');
    s3Mock
      .on(HeadObjectCommand)
      .rejects({ name: 'AccessDenied', $metadata: { httpStatusCode: 403 } });
    await expect(Uploader.upload({ inputDir: tmpDir, overwrite: false }, client)).rejects.toMatchObject(
      { name: 'AccessDenied' },
    );
  });

  it('overwrites by default (overwrite omitted)', async () => {
    touch(tmpDir, 'file.txt');
    // HeadObject not called at all — skip check entirely
    await Uploader.upload({ inputDir: tmpDir }, client);
    expect(s3Mock.calls()).toHaveLength(0);
    expect(MockUpload).toHaveBeenCalledTimes(1);
  });

  it('throws when inputDir is empty string', async () => {
    await expect(
      Uploader.upload({ inputDir: '' }, client),
    ).rejects.toThrow('inputDir must not be empty');
  });

  it('throws when inputDir does not exist', async () => {
    await expect(
      Uploader.upload({ inputDir: '/nonexistent/path/xyz-prescient' }, client),
    ).rejects.toThrow('does not exist');
  });

  it('throws when uploadBucket is not configured', async () => {
    const noBucketClient = new PrescientClient({
      endpointUrl: 'https://api.example.com',
      clientId: 'client-id',
      authUrl: 'https://login.microsoftonline.com',
      tenantId: 'tenant-id',
      uploadRole: 'arn:aws:iam::123456789012:role/upload-role',
    });
    touch(tmpDir, 'file.txt');
    await expect(Uploader.upload({ inputDir: tmpDir }, noBucketClient)).rejects.toThrow(
      'uploadBucket is not configured',
    );
  });
});

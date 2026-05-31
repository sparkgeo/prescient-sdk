import * as fs from 'fs';
import * as path from 'path';

import { S3Client, HeadObjectCommand } from '@aws-sdk/client-s3';
import { Upload } from '@aws-sdk/lib-storage';

import { PrescientClient } from './client';
import { UploadOptions } from './types';

/**
 * Uploads files from a local directory to the Prescient upload bucket.
 *
 * @example
 * await Uploader.upload({ inputDir: '/path/to/data' });
 *
 * @example Resume a partial upload without overwriting already-uploaded files
 * await Uploader.upload({ inputDir: '/path/to/data', overwrite: false });
 */
export class Uploader {
  /**
   * Upload all files under `opts.inputDir` to the configured upload bucket.
   *
   * Each file is stored at `<dir-name>/<relative-path>` where `<dir-name>` is
   * the last component of `opts.inputDir`.  Patterns in `opts.exclude` are
   * matched against the basename for single-segment patterns (e.g. `*.txt`) or
   * against the full relative path for multi-segment patterns (e.g. `logs/*`),
   * mirroring Python `pathlib.Path.match` semantics.  `**` matches zero or more
   * path segments.  `[abc]` matches any character in the set.  `{a,b}` matches
   * either alternative.  Symlinks inside `opts.inputDir` are not followed.
   *
   * @param opts - Upload options.
   * @param client - PrescientClient to use; a default client is constructed
   *   from environment variables when omitted.
   * @throws Error if `opts.inputDir` is empty.
   * @throws Error if `opts.inputDir` traverses above the working directory.
   * @throws Error if `opts.inputDir` does not exist or is not a directory.
   * @throws Error if `uploadBucket` is not configured on the client settings.
   */
  static async upload(opts: UploadOptions, client?: PrescientClient): Promise<void> {
    if (!opts.inputDir || opts.inputDir.trim() === '') {
      throw new Error('inputDir must not be empty.');
    }

    // Reject relative paths that escape the working directory (e.g. ../../etc).
    // Absolute paths are accepted as-is — the caller is responsible for their scope.
    if (path.normalize(opts.inputDir).startsWith('..')) {
      throw new Error(
        `inputDir must not traverse above the working directory: ${opts.inputDir}`,
      );
    }

    const resolvedDir = path.resolve(opts.inputDir);

    if (!fs.existsSync(resolvedDir) || !fs.statSync(resolvedDir).isDirectory()) {
      throw new Error(`inputDir does not exist or is not a directory: ${opts.inputDir}`);
    }

    const prescientClient = client ?? new PrescientClient();

    const bucket = prescientClient.settings.uploadBucket;
    if (!bucket) {
      throw new Error(
        'uploadBucket is not configured; set PRESCIENT_UPLOAD_BUCKET to upload files.',
      );
    }

    // Credential provider function — the AWS SDK calls this before each request
    // and automatically refreshes before the token expires, so long-running
    // uploads never hit ExpiredTokenException mid-flight.
    const s3 = new S3Client({
      region: prescientClient.settings.awsRegion ?? 'us-east-1',
      credentials: async () => {
        const c = await prescientClient.uploadBucketCredentials();
        return {
          accessKeyId: c.accessKeyId,
          secretAccessKey: c.secretAccessKey,
          sessionToken: c.sessionToken,
          expiration: new Date(c.expiresAt),
        };
      },
    });

    const overwrite = opts.overwrite ?? true;
    const dirName = path.basename(resolvedDir);
    const files = Uploader._walk(resolvedDir);

    // Pre-compile exclude patterns once — avoids N×M RegExp constructions in the loop.
    const excludePatterns = (opts.exclude ?? []).map(pat => Uploader._compileGlob(pat));

    // Files are uploaded sequentially. Add bounded parallelism here if
    // upload throughput becomes a bottleneck for large directories.
    for (const file of files) {
      const relative = path.relative(resolvedDir, file).replace(/\\/g, '/');
      const excluded = excludePatterns.some(({ regex, useBasename }) =>
        regex.test(useBasename ? path.basename(relative) : relative),
      );
      if (excluded) continue;
      const key = `${dirName}/${relative}`;
      await Uploader._putFile(file, bucket, key, s3, overwrite);
    }
  }

  /** Recursively list all regular files under `dir`. Symlinks are not followed. */
  private static _walk(dir: string, acc: string[] = []): string[] {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (err: unknown) {
      const e = err as NodeJS.ErrnoException;
      throw new Error(`Cannot read directory ${dir}: ${e.message}`);
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        Uploader._walk(full, acc);
      } else if (entry.isFile() && !entry.isSymbolicLink()) {
        acc.push(full);
      }
    }
    return acc;
  }

  /**
   * Compile a glob pattern into a regex and a flag indicating whether to test
   * against the basename only (patterns with no `/`) or the full relative path.
   *
   * Supported syntax:
   *   `*`      — any characters within a single path segment
   *   `**`     — zero or more complete path segments
   *   `?`      — any single non-separator character
   *   `[abc]`  — character class (supports ranges and `!` negation)
   *   `{a,b}`  — brace expansion (alternatives, no nesting)
   */
  private static _compileGlob(pattern: string): { regex: RegExp; useBasename: boolean } {
    const p = pattern.replace(/\\/g, '/');
    const useBasename = !p.includes('/');
    let regStr = '^';
    for (let i = 0; i < p.length; ) {
      if (p[i] === '*' && p[i + 1] === '*') {
        if (p[i + 2] === '/') {
          // **/ — zero or more path segments (including none), consuming the slash
          regStr += '(?:.*/)?';
          i += 3;
        } else {
          // ** at end or immediately before a non-slash character
          regStr += '.*';
          i += 2;
        }
      } else if (p[i] === '*') {
        regStr += '[^/]*';
        i += 1;
      } else if (p[i] === '?') {
        regStr += '[^/]';
        i += 1;
      } else if (p[i] === '[') {
        const end = p.indexOf(']', i + 1);
        if (end === -1) {
          regStr += '\\[';
          i += 1;
        } else {
          let cls = p.slice(i + 1, end);
          const negate = cls.startsWith('!') ? '^' : '';
          if (negate) cls = cls.slice(1);
          // Escape regex metacharacters inside the class, preserving - for ranges
          cls = cls.replace(/[.+*?${}()|[\]\\]/g, '\\$&');
          regStr += `[${negate}${cls}]`;
          i = end + 1;
        }
      } else if (p[i] === '{') {
        const end = p.indexOf('}', i + 1);
        if (end === -1) {
          regStr += '\\{';
          i += 1;
        } else {
          // Expand {a,b} → (?:a|b), applying * and ? substitution within each alternative
          const alts = p
            .slice(i + 1, end)
            .split(',')
            .map(alt =>
              alt
                .replace(/[.+^${}()|[\]\\]/g, '\\$&')
                .replace(/\*/g, '[^/]*')
                .replace(/\?/g, '[^/]'),
            );
          regStr += `(?:${alts.join('|')})`;
          i = end + 1;
        }
      } else {
        regStr += p[i].replace(/[.+^${}()|[\]\\]/g, '\\$&');
        i += 1;
      }
    }
    return { regex: new RegExp(regStr + '$'), useBasename };
  }

  private static async _putFile(
    file: string,
    bucket: string,
    key: string,
    s3: S3Client,
    overwrite: boolean,
  ): Promise<void> {
    if (!overwrite) {
      try {
        await s3.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
        return; // object exists — skip
      } catch (err: unknown) {
        const e = err as { name?: string };
        // Only treat canonical not-found error names as "object absent" — any
        // other error (including AccessDenied returned as 404 by some bucket
        // policies) is re-thrown so the caller sees the real failure.
        if (e.name !== 'NotFound' && e.name !== 'NoSuchKey') {
          throw err;
        }
        // NotFound / NoSuchKey → object does not exist, proceed with upload
      }
    }

    const stream = fs.createReadStream(file);
    const upload = new Upload({
      client: s3,
      params: {
        Bucket: bucket,
        Key: key,
        Body: stream,
      },
    });
    try {
      await upload.done();
    } finally {
      stream.destroy();
    }
  }
}

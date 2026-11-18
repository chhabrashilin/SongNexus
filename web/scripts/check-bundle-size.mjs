// Fails the build if the JavaScript loaded by index.html exceeds the budget.
// Lazy-loaded chunks (e.g. the Firebase Auth SDK) are excluded by design.
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {gzipSync} from 'node:zlib';

const BUDGET_BYTES = 200 * 1024;
const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const html = readFileSync(join(dist, 'index.html'), 'utf8');
const scripts = [
  ...html.matchAll(
    /<(?:script|link)[^>]+(?:src|href)="\/(assets\/[^"]+\.js)"/g,
  ),
].map(m => m[1]);

let total = 0;
for (const file of scripts) {
  const size = gzipSync(readFileSync(join(dist, file))).length;
  total += size;
  console.log(`${file}: ${(size / 1024).toFixed(1)} KB gzip`);
}
console.log(
  `initial JS: ${(total / 1024).toFixed(1)} KB gzip (budget ${BUDGET_BYTES / 1024} KB)`,
);
if (total > BUDGET_BYTES) {
  console.error('Bundle budget exceeded.');
  process.exit(1);
}

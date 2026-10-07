// Google TypeScript style via gts, applied to the whole web package.
import gts from 'gts';

export default [
  {
    ignores: [
      'dist/',
      'node_modules/',
      'playwright-report/',
      'test-results/',
      'src/api/schema.d.ts',
    ],
  },
  ...gts,
  {files: ['eslint.config.js'], languageOptions: {sourceType: 'module'}},
  {
    files: ['scripts/**/*.mjs'],
    languageOptions: {
      sourceType: 'module',
      globals: {console: 'readonly', process: 'readonly', URL: 'readonly'},
    },
  },
];

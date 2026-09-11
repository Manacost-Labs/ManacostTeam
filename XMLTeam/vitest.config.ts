import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    testTimeout: 60_000,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      exclude: ['src/index.ts', 'src/node.ts', 'src/semantic/index.ts'],
      reporter: ['text', 'html', 'json-summary'],
      reportsDirectory: 'coverage',
      // Baseline on 2026-09-04: 98% statements/lines, 92% branches, 97% functions.
      // Gates sit a little below so that coverage cannot silently erode.
      thresholds: {
        statements: 95,
        lines: 95,
        functions: 93,
        branches: 85,
        'src/parser/**/*.ts': { statements: 93, lines: 93, branches: 85 },
        'src/state/**/*.ts': { statements: 95, lines: 95, branches: 90 },
        'src/semantic/**/*.ts': { statements: 97, lines: 97, branches: 85 },
      },
    },
  },
});

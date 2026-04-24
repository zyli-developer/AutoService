import { describe, it, expect } from 'vitest';

describe('admin-portal api module', () => {
  it('does not hardcode localhost:8000 in its source', async () => {
    const src = await import('fs').then(fs =>
      fs.readFileSync(
        new URL('../api.ts', import.meta.url).pathname,
        'utf8'
      )
    );
    expect(src).not.toMatch(/localhost:8000/);
    expect(src).not.toMatch(/\$\{[^}]*hostname[^}]*\}:8000/);
  });

  it('SandboxReady does not hardcode localhost:8000', async () => {
    const src = await import('fs').then(fs =>
      fs.readFileSync(
        new URL('../components/wizard/SandboxReady.tsx', import.meta.url).pathname,
        'utf8'
      )
    );
    expect(src).not.toMatch(/localhost:8000/);
    expect(src).not.toMatch(/\$\{[^}]*hostname[^}]*\}:8000/);
  });
});

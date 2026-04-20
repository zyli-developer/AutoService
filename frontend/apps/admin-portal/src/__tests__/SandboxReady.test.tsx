/**
 * T1F.7 · SandboxReady tests
 *
 * Covers:
 *  - Renders sandbox URL + publish button before click
 *  - Happy path: POST /api/onboard/publish → shows artifact + runbook + archive paths
 *  - Gate blocked (409): shows blocking_reasons list
 *  - Generic error (500): shows error surface
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { useAdminStore } from '../store/adminStore';
import { SandboxReady } from '../components/wizard/SandboxReady';

// fetch is shimmed via vi.stubGlobal so we can return status/body pairs.
function mockFetch(response: {
  status: number;
  body: Record<string, unknown>;
}) {
  return vi.fn(async () =>
    Promise.resolve({
      ok: response.status >= 200 && response.status < 300,
      status: response.status,
      json: async () => response.body,
    } as Response),
  );
}

describe('SandboxReady (T1F.7)', () => {
  beforeEach(() => {
    useAdminStore.setState({ tenantId: 'acme-corp' });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders sandbox URL and publish button before click', () => {
    render(<SandboxReady />);
    expect(screen.getByTestId('sandbox-ready')).toBeInTheDocument();
    expect(screen.getByTestId('sandbox-url').textContent).toContain(
      'acme-corp.sandbox.onesync',
    );
    expect(screen.getByTestId('btn-publish')).toBeInTheDocument();
    // Before clicking, neither success nor blocked states should show.
    expect(screen.queryByTestId('publish-result')).not.toBeInTheDocument();
    expect(screen.queryByTestId('publish-blocked')).not.toBeInTheDocument();
  });

  it('TC-T1F7-SR-A: happy path — shows artifact + runbook paths on 200', async () => {
    const fetchMock = mockFetch({
      status: 200,
      body: {
        status: 'published',
        tenant_id: 'acme-corp',
        artifact: '.autoservice/published/tenant_acme-corp_publish_1713600000.tar.gz',
        artifact_sha256: 'abc123',
        runbook: '.autoservice/published/acme-corp_PUBLISH_RUNBOOK.md',
        record: '.autoservice/published/acme-corp.json',
        archived_to: '.autoservice/archived/acme-corp_1713600000',
        gate: { blocking_reasons: [] },
      },
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SandboxReady />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-publish'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('publish-result')).toBeInTheDocument();
    });

    // Verify fetch called with the right URL + body.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [url, init] = call;
    expect(url).toMatch(/\/api\/onboard\/publish$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ tenant_id: 'acme-corp' });

    // Result sections rendered.
    expect(screen.getByTestId('result-artifact').textContent).toContain(
      'tenant_acme-corp_publish_',
    );
    expect(screen.getByTestId('result-runbook').textContent).toContain(
      'PUBLISH_RUNBOOK.md',
    );
    expect(screen.getByTestId('result-archived').textContent).toContain(
      'archived/acme-corp_',
    );

    // Publish button is gone once result is shown.
    expect(screen.queryByTestId('btn-publish')).not.toBeInTheDocument();
  });

  it('TC-T1F7-SR-B: gate blocked (409) — shows blocking_reasons list', async () => {
    const fetchMock = mockFetch({
      status: 409,
      body: {
        error: 'publish blocked by gate',
        tenant_id: 'acme-corp',
        status: 'blocked',
        blocking_reasons: [
          'rehearsal has 3 un-reviewed dialogs',
          'compliance critical issue: missing-privacy-policy',
        ],
      },
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SandboxReady />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-publish'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('publish-blocked')).toBeInTheDocument();
    });

    const reasons = screen.getByTestId('blocking-reasons');
    expect(reasons.textContent).toContain('un-reviewed dialogs');
    expect(reasons.textContent).toContain('missing-privacy-policy');
    expect(screen.getByTestId('blocking-reason-0')).toBeInTheDocument();
    expect(screen.getByTestId('blocking-reason-1')).toBeInTheDocument();

    // Publish button remains available so the user can retry after fixing.
    expect(screen.getByTestId('btn-publish')).toBeInTheDocument();
    // No success result surfaced.
    expect(screen.queryByTestId('publish-result')).not.toBeInTheDocument();
  });

  it('TC-T1F7-SR-D: override — blocked 409 then force-publish with signer succeeds', async () => {
    // First call: 409 with blocking_reasons; second call: 200 override success.
    const fetchMock = vi
      .fn()
      // 1st call — blocked
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          error: 'publish blocked by gate',
          tenant_id: 'acme-corp',
          status: 'blocked',
          blocking_reasons: ['compliance.risk_level=critical'],
        }),
      } as Response)
      // 2nd call — override accepted
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'published',
          tenant_id: 'acme-corp',
          artifact: '.autoservice/published/acme-corp.tar.gz',
          runbook: '.autoservice/published/acme-corp_PUBLISH_RUNBOOK.md',
          archived_to: '.autoservice/archived/acme-corp_1713600000',
        }),
      } as Response);
    vi.stubGlobal('fetch', fetchMock);

    render(<SandboxReady />);

    // Step 1: normal publish → blocked
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-publish'));
    });
    await waitFor(() => {
      expect(screen.getByTestId('publish-blocked')).toBeInTheDocument();
    });
    // Override panel appears inside the blocked section.
    expect(screen.getByTestId('publish-override')).toBeInTheDocument();
    const overrideBtn = screen.getByTestId(
      'btn-override-publish',
    ) as HTMLButtonElement;
    expect(overrideBtn.disabled).toBe(true); // empty signer → disabled

    // Step 2: enter signer email → button enables
    const input = screen.getByTestId(
      'override-signer-input',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'alice@platform.com' } });
    expect(overrideBtn.disabled).toBe(false);

    // Step 3: click override → second fetch with override=true + signer, result appears
    await act(async () => {
      fireEvent.click(overrideBtn);
    });
    await waitFor(() => {
      expect(screen.getByTestId('publish-result')).toBeInTheDocument();
    });

    // Verify the 2nd call carried override + signer.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondCall = fetchMock.mock.calls[1] as unknown as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(secondCall[1].body as string)).toEqual({
      tenant_id: 'acme-corp',
      override: true,
      signer: 'alice@platform.com',
    });

    // Blocked panel disappears once result surfaces.
    expect(screen.queryByTestId('publish-blocked')).not.toBeInTheDocument();
  });

  it('TC-T1F7-SR-C: generic error (500) — shows error message', async () => {
    const fetchMock = mockFetch({
      status: 500,
      body: { error: 'internal boom' },
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SandboxReady />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-publish'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('publish-error')).toBeInTheDocument();
    });
    // Success + blocked states must NOT render when a generic error happens.
    expect(screen.queryByTestId('publish-result')).not.toBeInTheDocument();
    expect(screen.queryByTestId('publish-blocked')).not.toBeInTheDocument();
    // Publish button remains (user can retry).
    expect(screen.getByTestId('btn-publish')).toBeInTheDocument();
  });
});

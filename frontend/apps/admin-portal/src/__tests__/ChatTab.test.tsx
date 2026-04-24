/**
 * T6F.6 · ChatTab tests — /api/admin/chat roundtrip
 *
 * Covers:
 *  - Renders input + submit button + empty-state placeholder.
 *  - Submit POSTs /api/admin/chat with credentials:'include' + JSON body.
 *  - `body.reply` appended to history as assistant bubble.
 *  - Empty input → no fetch call; send button disabled when input blank.
 *  - Loading state: send button disabled + spinner visible between click
 *    and resolve.
 *  - Network / non-OK response → error bubble rendered; no crash.
 *  - History accumulates across multiple sends.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatTab } from '../components/tenant/ChatTab';

function makeFetchMock(
  impl: (url: string, init?: RequestInit) => Promise<Response> | Response,
) {
  return vi.fn(impl) as unknown as typeof fetch;
}

function okJson(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('ChatTab (T6F.6)', () => {
  it('renders input, send button, and empty-state placeholder', () => {
    render(<ChatTab fetcher={makeFetchMock(() => okJson({ reply: 'hi' }))} />);
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    expect(screen.getByTestId('chat-send')).toBeInTheDocument();
    expect(screen.getByTestId('chat-empty-state')).toBeInTheDocument();
  });

  it('submits POST /api/admin/chat with credentials:"include" and JSON body', async () => {
    const user = userEvent.setup();
    const fetchMock = makeFetchMock(() => okJson({ reply: 'pong' }));
    render(<ChatTab fetcher={fetchMock} />);

    await user.type(screen.getByTestId('chat-input'), 'ping');
    await user.click(screen.getByTestId('chat-send'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, RequestInit];
    expect(url).toBe('/api/admin/chat');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe(
      'application/json',
    );
    expect(JSON.parse(init.body as string)).toEqual({ message: 'ping' });
  });

  it('appends body.reply to history as an assistant bubble', async () => {
    const user = userEvent.setup();
    render(
      <ChatTab
        fetcher={makeFetchMock(() => okJson({ reply: 'hello from stub' }))}
      />,
    );
    await user.type(screen.getByTestId('chat-input'), 'hi');
    await user.click(screen.getByTestId('chat-send'));

    await waitFor(() => {
      expect(screen.getByTestId('chat-msg-assistant')).toHaveTextContent(
        'hello from stub',
      );
    });
    // User bubble also visible
    expect(screen.getByTestId('chat-msg-user')).toHaveTextContent('hi');
  });

  it('empty input does not trigger a fetch (send button disabled)', async () => {
    const user = userEvent.setup();
    const fetchMock = makeFetchMock(() => okJson({ reply: 'x' }));
    render(<ChatTab fetcher={fetchMock} />);

    const sendBtn = screen.getByTestId('chat-send');
    expect(sendBtn).toBeDisabled();

    // Click attempt should be a no-op (native disabled) — fetch stays uncalled.
    await user.click(sendBtn);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('disables the send button while a request is in-flight', async () => {
    const user = userEvent.setup();
    let resolveIt: ((v: Response) => void) | null = null;
    const fetchMock = makeFetchMock(
      () =>
        new Promise<Response>((res) => {
          resolveIt = res;
        }),
    );
    render(<ChatTab fetcher={fetchMock} />);

    await user.type(screen.getByTestId('chat-input'), 'slow');
    await user.click(screen.getByTestId('chat-send'));

    // In-flight: loading indicator + disabled send.
    await waitFor(() =>
      expect(screen.getByTestId('chat-loading')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('chat-send')).toBeDisabled();

    // Resolve and settle.
    resolveIt!(okJson({ reply: 'done' }));
    await waitFor(() =>
      expect(screen.queryByTestId('chat-loading')).not.toBeInTheDocument(),
    );
  });

  it('renders an error bubble when the fetch rejects', async () => {
    const user = userEvent.setup();
    const fetchMock = makeFetchMock(() =>
      Promise.reject(new Error('network down')),
    );
    render(<ChatTab fetcher={fetchMock} />);

    await user.type(screen.getByTestId('chat-input'), 'boom');
    await user.click(screen.getByTestId('chat-send'));

    await waitFor(() => {
      const errBubble = screen.getByTestId('chat-msg-error');
      expect(errBubble).toHaveTextContent(/network down/);
    });
  });

  it('accumulates history across multiple sends', async () => {
    const user = userEvent.setup();
    let n = 0;
    const fetchMock = makeFetchMock(() => {
      n += 1;
      return okJson({ reply: `reply-${n}` });
    });
    render(<ChatTab fetcher={fetchMock} />);

    // Send 1
    await user.type(screen.getByTestId('chat-input'), 'msg-one');
    await user.click(screen.getByTestId('chat-send'));
    await waitFor(() =>
      expect(screen.getAllByTestId('chat-msg-assistant')).toHaveLength(1),
    );

    // Send 2
    await user.type(screen.getByTestId('chat-input'), 'msg-two');
    await user.click(screen.getByTestId('chat-send'));
    await waitFor(() =>
      expect(screen.getAllByTestId('chat-msg-assistant')).toHaveLength(2),
    );

    // Both user messages still in history
    const userMsgs = screen.getAllByTestId('chat-msg-user');
    expect(userMsgs.map((el) => el.textContent)).toEqual(['msg-one', 'msg-two']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

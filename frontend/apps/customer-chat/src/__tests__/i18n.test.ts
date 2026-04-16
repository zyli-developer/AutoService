import { describe, it, expect } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { createElement } from 'react';
import { createI18n, I18nextProvider } from '@autoservice/i18n';

// ---------------------------------------------------------------------------
// Helper: render a component wrapped in an isolated i18n provider
// ---------------------------------------------------------------------------
function renderWithI18n(component: React.ReactElement, lng: string = 'zh-CN') {
  const i18n = createI18n(lng);
  return { ...render(createElement(I18nextProvider, { i18n }, component)), i18n };
}

async function waitForI18n(i18n: ReturnType<typeof createI18n>) {
  if (i18n.isInitialized) return;
  await new Promise<void>((res) => i18n.on('initialized', res));
}

// ---------------------------------------------------------------------------
// TC-063: zh-CN locale — t('connection.lost') returns correct Chinese
// ---------------------------------------------------------------------------
describe('i18n', () => {
  it('TC-063: zh-CN locale — t("connection.lost") returns Chinese text', async () => {
    const i18n = createI18n('zh-CN');
    await waitForI18n(i18n);
    expect(i18n.t('connection.lost')).toBe('连接中断');
  });

  // TC-064: en locale — t('connection.lost') returns correct English
  it('TC-064: en locale — t("connection.lost") returns English text', async () => {
    const i18n = createI18n('en');
    await waitForI18n(i18n);
    expect(i18n.t('connection.lost')).toBe('Connection lost');
  });

  // TC-065: unknown language falls back to en
  it('TC-065: unknown language falls back to en', async () => {
    const i18n = createI18n('fr');  // no French locale defined
    await waitForI18n(i18n);
    expect(i18n.t('connection.lost')).toBe('Connection lost');
  });

  // TC-066: t('connection.replaying', { count: 5 }) contains interpolated number
  it('TC-066: t("connection.replaying", { count: 5 }) contains interpolated number', async () => {
    const i18n = createI18n('zh-CN');
    await waitForI18n(i18n);
    const result = i18n.t('connection.replaying', { count: 5 });
    expect(result).toContain('5');
    expect(result).toContain('同步');
  });

  // TC-067: ConnectionBanner renders i18n text (no hardcoded Chinese in en mode)
  it('TC-067: ConnectionBanner uses i18n text — no hardcoded Chinese in en mode', async () => {
    const { ConnectionBanner } = await import('../components/ConnectionBanner');
    renderWithI18n(createElement(ConnectionBanner, { status: 'closed' }), 'en');
    const banner = screen.getByTestId('connection-banner');
    expect(banner.textContent).toBe('Connection lost');
    expect(banner.textContent).not.toMatch(/连接|断线/);
  });

  // TC-068: ChatInput placeholder uses i18n text
  it('TC-068: ChatInput placeholder uses i18n text', async () => {
    const { ChatInput } = await import('../components/ChatInput');
    renderWithI18n(createElement(ChatInput, { onSend: () => {} }), 'en');
    const input = screen.getByTestId('chat-input') as HTMLTextAreaElement;
    expect(input.placeholder).toBe('Type a message...');
    // zh-CN placeholder
    const { unmount } = renderWithI18n(createElement(ChatInput, { onSend: () => {} }), 'zh-CN');
    const inputs = screen.getAllByTestId('chat-input') as HTMLTextAreaElement[];
    expect(inputs[inputs.length - 1].placeholder).toBe('输入消息...');
    unmount();
  });

  // TC-069: TypingIndicator uses i18n aria-label
  it('TC-069: TypingIndicator aria-label uses i18n text', async () => {
    const { TypingIndicator } = await import('../components/TypingIndicator');
    renderWithI18n(createElement(TypingIndicator, { visible: true }), 'en');
    const indicators = screen.getAllByTestId('typing-indicator');
    expect(indicators[indicators.length - 1]).toHaveAttribute('aria-label', 'Typing...');
  });

  // TC-070: switching language re-renders component with new text
  it('TC-070: language switch re-renders component with updated text', async () => {
    const { ConnectionBanner } = await import('../components/ConnectionBanner');
    const i18n = createI18n('en');
    await waitForI18n(i18n);

    render(
      createElement(I18nextProvider, { i18n },
        createElement(ConnectionBanner, { status: 'closed' }),
      ),
    );

    expect(screen.getByTestId('connection-banner').textContent).toBe('Connection lost');

    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });

    expect(screen.getByTestId('connection-banner').textContent).toBe('连接中断');
  });
});

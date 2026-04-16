import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChannelConfigStep } from '../components/wizard/ChannelConfigStep';

describe('ChannelConfigStep', () => {
  it('TC-01: renders with Web pre-checked and Feishu disabled', () => {
    render(<ChannelConfigStep tenantId="tenant-001" />);
    const webCheckbox = screen.getByLabelText('Web 在线客服') as HTMLInputElement;
    const feishuCheckbox = screen.getByLabelText('飞书 IM') as HTMLInputElement;
    expect(webCheckbox.checked).toBe(true);
    expect(feishuCheckbox.disabled).toBe(true);
  });

  it('TC-02: clicking generate shows URL with tenantId', async () => {
    const user = userEvent.setup();
    render(<ChannelConfigStep tenantId="tenant-001" />);
    await user.click(screen.getByTestId('btn-generate-url'));
    const urlEl = screen.getByTestId('generated-url');
    expect(urlEl).toHaveTextContent('https://tenant-001.autoservice.ai/chat');
  });

  it('TC-03: Web checkbox is checked by default', () => {
    render(<ChannelConfigStep tenantId="tenant-002" />);
    const webCheckbox = screen.getByLabelText('Web 在线客服') as HTMLInputElement;
    expect(webCheckbox.checked).toBe(true);
  });
});

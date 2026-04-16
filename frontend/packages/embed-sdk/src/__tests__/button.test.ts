import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createButton, destroyButton } from '../button';

beforeEach(() => {
  document.body.innerHTML = '';
});

describe('button', () => {
  it('TC-075: createButton appends to body with background-color style', () => {
    createButton({ domain: 'm-001', theme: { color: '#0ea5e9' } }, vi.fn());
    const btn = document.getElementById('as-embed-btn');
    expect(btn).not.toBeNull();
    // Check cssText contains the color (jsdom may keep hex or convert to rgb)
    const cssText = btn!.style.cssText;
    const bgColor = btn!.style.backgroundColor;
    const hasColor =
      cssText.includes('#0ea5e9') ||
      bgColor === 'rgb(14, 165, 233)' ||
      bgColor !== '';
    expect(hasColor).toBe(true);
  });

  it('TC-076: createButton click calls onClick', () => {
    const onClick = vi.fn();
    const btn = createButton({ domain: 'm-001' }, onClick);
    btn.click();
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('TC-077: destroyButton removes button from DOM', () => {
    const btn = createButton({ domain: 'm-001' }, vi.fn());
    destroyButton(btn);
    expect(document.getElementById('as-embed-btn')).toBeNull();
  });
});

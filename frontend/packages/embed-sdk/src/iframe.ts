import type { EmbedConfig } from './config';
import { buildContainerStyle } from './theme';
import { buildIframeSrc } from './config';

export function createIframe(config: EmbedConfig): HTMLDivElement {
  const container = document.createElement('div');
  container.id = 'as-embed-container';
  container.style.cssText = buildContainerStyle(config.theme);

  const iframe = document.createElement('iframe');
  iframe.src = buildIframeSrc(config);
  iframe.style.cssText =
    'width: 100%; height: 100%; border: none; border-radius: 12px;';
  iframe.setAttribute('allow', 'microphone');

  container.appendChild(iframe);
  document.body.appendChild(container);
  return container;
}

export function showIframe(container: HTMLElement): void {
  container.style.display = 'block';
}

export function hideIframe(container: HTMLElement): void {
  container.style.display = 'none';
}

import type { EmbedConfig } from './config';
import { buildButtonStyle } from './theme';

const CHAT_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;

export function createButton(
  config: EmbedConfig,
  onClick: () => void,
): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.id = 'as-embed-btn';
  btn.setAttribute('aria-label', 'Open chat');
  btn.style.cssText = buildButtonStyle(config.theme);
  btn.innerHTML = CHAT_ICON_SVG;
  btn.addEventListener('click', onClick);
  document.body.appendChild(btn);
  return btn;
}

export function destroyButton(btn: HTMLButtonElement): void {
  btn.remove();
}

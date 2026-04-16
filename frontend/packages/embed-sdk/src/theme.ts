import type { EmbedTheme } from './config';

export function buildButtonStyle(theme: EmbedTheme = {}): string {
  const { color = '#0ea5e9', position = 'bottom-right', zIndex = 9999 } = theme;
  const side = position === 'bottom-right' ? 'right: 24px' : 'left: 24px';
  return [
    'position: fixed',
    'bottom: 24px',
    side,
    `z-index: ${zIndex}`,
    'width: 56px',
    'height: 56px',
    'border-radius: 50%',
    'border: none',
    'cursor: pointer',
    `background-color: ${color}`,
    'box-shadow: 0 4px 12px rgba(0,0,0,0.2)',
    'display: flex',
    'align-items: center',
    'justify-content: center',
  ].join('; ');
}

export function buildContainerStyle(theme: EmbedTheme = {}): string {
  const { position = 'bottom-right', zIndex = 9999 } = theme;
  const side = position === 'bottom-right' ? 'right: 24px' : 'left: 24px';
  return [
    'position: fixed',
    'bottom: 96px',
    side,
    `z-index: ${zIndex - 1}`,
    'width: 380px',
    'height: 600px',
    'display: none',
    'box-shadow: 0 8px 32px rgba(0,0,0,0.2)',
    'border-radius: 12px',
    'overflow: hidden',
  ].join('; ');
}

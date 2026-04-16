import type { EmbedConfig } from './config';
import { parseScriptConfig } from './config';
import { createButton } from './button';
import { createIframe, showIframe, hideIframe } from './iframe';

let isOpen = false;
let iframeContainer: HTMLElement | null = null;

export function init(config: EmbedConfig): void {
  // Reset state for this init call
  isOpen = false;

  // 创建 iframe（初始隐藏）
  iframeContainer = createIframe(config);

  // 监听 iframe postMessage 关闭
  const onMessage = (ev: MessageEvent) => {
    if (ev.data?.type === 'as:close' && iframeContainer) {
      hideIframe(iframeContainer);
      isOpen = false;
    }
  };
  window.addEventListener('message', onMessage);

  // 创建浮动按钮
  createButton(config, () => {
    if (!iframeContainer) return;
    isOpen = !isOpen;
    if (isOpen) {
      showIframe(iframeContainer);
      config.onOpen?.();
    } else {
      hideIframe(iframeContainer);
      config.onClose?.();
    }
  });

  // 挂到 window
  (window as unknown as Record<string, unknown>).AsEmbed = { init };
}

function autoInit(): void {
  const scripts = document.querySelectorAll<HTMLScriptElement>(
    'script[data-domain]',
  );
  if (scripts.length === 0) return;
  const script = scripts[scripts.length - 1]; // 最后一个（一般只有一个）
  const config = parseScriptConfig(script);
  if (config) init(config);
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoInit);
  } else {
    autoInit();
  }
}

// 同时支持手动调用
(window as unknown as Record<string, unknown>).AsEmbed = { init };

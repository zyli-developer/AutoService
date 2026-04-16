export interface EmbedTheme {
  color?: string;
  position?: 'bottom-right' | 'bottom-left';
  zIndex?: number;
}

export interface EmbedConfig {
  domain: string;
  chatUrl?: string;
  lang?: string;
  theme?: EmbedTheme;
  onOpen?: () => void;
  onClose?: () => void;
}

export function parseScriptConfig(script: HTMLScriptElement): EmbedConfig | null {
  const domain = script.getAttribute('data-domain');
  if (!domain) return null;
  return {
    domain,
    lang: script.getAttribute('data-lang') ?? 'zh-CN',
    theme: {
      color: script.getAttribute('data-theme-color') ?? '#0ea5e9',
      position:
        (script.getAttribute('data-position') as EmbedTheme['position']) ??
        'bottom-right',
    },
  };
}

export function buildIframeSrc(config: EmbedConfig): string {
  const base = config.chatUrl ?? '/chat';
  const params = new URLSearchParams({
    domain: config.domain,
    lang: config.lang ?? 'zh-CN',
    embed: '1',
  });
  return `${base}?${params.toString()}`;
}

export interface VoiceIframeOpts {
  baseUrl: string;
  call_id: string;
  tenant_id?: string;
  customer_id?: string;
  systemRole?: string;
  greeting?: string;
  comfortText?: string;
  mode?: 'e2e' | 'split';
  lang?: string;
}

export function buildVoiceIframeUrl(opts: VoiceIframeOpts): string {
  const url = new URL(opts.baseUrl);
  url.searchParams.set('embed', '1');
  url.searchParams.set('call_id', opts.call_id);

  const optional: Array<[string, string | undefined]> = [
    ['tenant_id', opts.tenant_id],
    ['customer_id', opts.customer_id],
    ['systemRole', opts.systemRole],
    ['greeting', opts.greeting],
    ['comfortText', opts.comfortText],
    ['mode', opts.mode],
    ['lang', opts.lang],
  ];

  for (const [k, v] of optional) {
    if (v !== undefined && v !== '') url.searchParams.set(k, v);
  }

  return url.toString();
}

export type VoiceCallState =
  | 'idle'
  | 'connecting'
  | 'greeting'
  | 'talking'
  | 'ending'
  | 'ended'
  | 'error';

export type VoicePostMessage =
  | { type: 'as:voice:ready' }
  | { type: 'as:voice:state'; state: VoiceCallState }
  | { type: 'as:voice:transcript'; role: 'user' | 'bot'; text: string; interim: boolean }
  | { type: 'as:voice:error'; code: string; message: string }
  | { type: 'as:voice:close' }
  | { type: 'as:voice:hangup' };

const MESSAGE_TYPES = new Set<string>([
  'as:voice:ready',
  'as:voice:state',
  'as:voice:transcript',
  'as:voice:error',
  'as:voice:close',
  'as:voice:hangup',
]);

export function isVoiceMessage(data: unknown): data is VoicePostMessage {
  if (typeof data !== 'object' || data === null) return false;
  const t = (data as { type?: unknown }).type;
  return typeof t === 'string' && MESSAGE_TYPES.has(t);
}

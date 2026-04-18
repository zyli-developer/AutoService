import { useState } from 'react';
import { postForm } from '../../api';

const channelOptions = [
  { label: 'Web 在线客服', value: 'web', disabled: false },
  { label: '飞书 IM', value: 'feishu', disabled: true },
];

interface ChannelConfigStepProps {
  tenantId: string;
}

export function ChannelConfigStep({ tenantId }: ChannelConfigStepProps) {
  const [selectedChannels, setSelectedChannels] = useState<string[]>(['web']);
  const [generatedUrl, setGeneratedUrl] = useState<string | null>(null);

  const toggleChannel = (value: string) => {
    setSelectedChannels((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
  };

  const handleGenerate = async () => {
    try {
      const form = new FormData();
      form.append('tenant_id', tenantId);
      const resp = await postForm<{ urls?: { chat?: string } }>('/api/onboard/activate', form);
      setGeneratedUrl(resp.urls?.chat ?? null);
    } catch {
      setGeneratedUrl(`https://${tenantId}.sandbox.localhost`);
    }
  };

  return (
    <div data-testid="channel-config-step">
      <div className="cs-card">
        <div className="cs-ct">{'渠道配置'}</div>
        <div data-testid="channel-checkboxes" style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
          {channelOptions.map((opt) => (
            <label key={opt.value} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: opt.disabled ? 'var(--silver)' : 'var(--charcoal)' }}>
              <input
                type="checkbox"
                checked={selectedChannels.includes(opt.value)}
                disabled={opt.disabled}
                onChange={() => toggleChannel(opt.value)}
              />
              {opt.label}
            </label>
          ))}
        </div>
        <button
          data-testid="btn-generate-url"
          disabled={selectedChannels.length === 0}
          onClick={handleGenerate}
          style={{
            padding: '8px 16px',
            border: 'none',
            background: selectedChannels.length === 0 ? 'var(--oat)' : 'var(--m800)',
            color: selectedChannels.length === 0 ? 'var(--silver)' : '#fff',
            borderRadius: 9,
            fontSize: 12,
            fontWeight: 600,
            cursor: selectedChannels.length === 0 ? 'not-allowed' : 'pointer',
            fontFamily: 'var(--font-sans)',
          }}
        >
          {'生成链接'}
        </button>
        {generatedUrl && (
          <div className="cs-row" style={{ marginTop: 12 }}>
            <span data-testid="generated-url" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
              {generatedUrl}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

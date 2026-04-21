import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useAdminStore } from '../../store/adminStore';
import type { GenerationResult } from '../../store/adminStore';
import { postForm } from '../../api';

const INDUSTRY_VALUES = ['ecommerce', 'saas', 'finance', 'healthcare', 'education', 'general'] as const;
// Exported for any callers that need the raw value list.
export const INDUSTRY_OPTIONS = INDUSTRY_VALUES.map((value) => ({ value, labelKey: `admin.wizard.upload.industry.${value}` }));

const AGENT_ROLES = ['customer', 'translate', 'lead', 'triage'] as const;

interface Props { tenantId: string; onGenerated?: () => void; }

export function MaterialUploadStep({ tenantId, onGenerated }: Props) {
  const { t } = useTranslation();
  const [brandName, setBrandName] = useState('');
  const [industry, setIndustry] = useState('general');
  const [url, setUrl] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [generating, setGenerating] = useState(false);
  const generationResult = useAdminStore((s) => s.generationResult);
  const setGenerationResult = useAdminStore((s) => s.setGenerationResult);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const formData = new FormData();
      formData.append('brand_name', brandName || tenantId);
      formData.append('industry', industry);
      formData.append('website_url', url);
      for (const f of files) formData.append('files', f);
      const resp = await postForm<{ tenant_id: string; souls: Record<string, unknown>; files_parsed: number }>('/api/onboard/upload', formData);
      const souls: GenerationResult['souls'] = {};
      for (const role of AGENT_ROLES) {
        const s = (resp.souls as Record<string, any>)?.[role];
        souls[role] = { role, kbHitCount: s?.kb_hit_count ?? 0, mode: s?.mode ?? 'dry_run', warnings: s?.warnings ?? [] };
      }
      setGenerationResult({ tenantId: resp.tenant_id, souls, totalKbHits: Object.values(souls).reduce((sum, v) => sum + v.kbHitCount, 0), mode: 'ai', warnings: [] });
      onGenerated?.();
    } catch (e) {
      console.error('Upload failed:', e);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div data-testid="material-upload-step">
      <div className="cs-card hl">
        <div className="cs-ct"><span className="num">1</span>{t('admin.wizard.upload.title')}</div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, margin: '12px 0' }}>
          <div>
            <label style={{ fontSize: 11, color: 'var(--silver)', marginBottom: 4, display: 'block' }}>{t('admin.wizard.upload.brand')}</label>
            <input data-testid="input-brand" value={brandName} onChange={e => setBrandName(e.target.value)} placeholder={t('admin.wizard.upload.brand_placeholder')}
              style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--oat)', borderRadius: 9, fontSize: 13, fontFamily: 'var(--font-sans)', outline: 'none' }} />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--silver)', marginBottom: 4, display: 'block' }}>{t('admin.wizard.upload.industry')}</label>
            <select data-testid="select-industry" value={industry} onChange={e => setIndustry(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--oat)', borderRadius: 9, fontSize: 13, fontFamily: 'var(--font-sans)', outline: 'none', background: '#fff' }}>
              {INDUSTRY_OPTIONS.map(o => <option key={o.value} value={o.value}>{t(o.labelKey)}</option>)}
            </select>
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--silver)', marginBottom: 4, display: 'block' }}>{t('admin.wizard.upload.url')}</label>
            <input data-testid="input-url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com"
              style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--oat)', borderRadius: 9, fontSize: 13, fontFamily: 'var(--font-sans)', outline: 'none' }} />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'var(--silver)', marginBottom: 4, display: 'block' }}>{t('admin.wizard.upload.files')}</label>
            <label className="cs-file-picker">
              <input data-testid="file-upload" type="file" accept=".pdf,.csv,.txt" multiple
                onChange={e => setFiles(Array.from(e.target.files || []))}
                className="cs-file-input-hidden" />
              <span className="cs-file-picker-btn">{t('admin.wizard.upload.choose_file')}</span>
              <span className="cs-file-picker-hint">
                {files.length > 0
                  ? t('admin.wizard.upload.files_selected', { count: files.length })
                  : t('admin.wizard.upload.no_file_selected')}
              </span>
            </label>
          </div>
        </div>

        <button className="cs-btn ok" data-testid="btn-generate" onClick={handleGenerate} disabled={generating}
          style={{ width: '100%', marginTop: 8, opacity: generating ? 0.6 : 1 }}>
          {generating ? t('admin.wizard.upload.generating') : t('admin.wizard.upload.generate_agent')}
        </button>
      </div>

      {generationResult && (
        <div className="cs-card" style={{ marginTop: 14 }} data-testid="generation-result">
          <div className="cs-ct">{t('admin.wizard.upload.agent_init')}</div>
          {AGENT_ROLES.map(role => {
            const soul = generationResult.souls[role];
            return (
              <div className="cs-row" key={role} data-testid={`agent-status-${role}`}>
                <span>{role} Agent</span>
                <span style={{ color: soul ? 'var(--m600)' : 'var(--silver)', fontWeight: 700 }}>
                  {soul ? t('admin.wizard.upload.kb_hits', { count: soul.kbHitCount }) : '...'}
                </span>
              </div>
            );
          })}
          <div className="cs-pg ok" style={{ marginTop: 8 }}>
            {t('admin.wizard.upload.agents_ready', { count: 4, total: generationResult.totalKbHits })}
          </div>
        </div>
      )}
    </div>
  );
}

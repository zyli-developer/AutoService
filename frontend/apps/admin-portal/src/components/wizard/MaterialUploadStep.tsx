import { useState } from 'react';
import { Button, Card, Form, Input, Select, Space, Tag, Typography, Upload, Alert, Spin } from 'antd';
import { InboxOutlined, CheckCircleOutlined, WarningOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd';
import { useAdminStore } from '../../store/adminStore';
import type { GenerationResult } from '../../store/adminStore';

export const INDUSTRY_OPTIONS = [
  { label: '电商', value: 'ecommerce' },
  { label: 'SaaS', value: 'saas' },
  { label: '金融', value: 'finance' },
  { label: '医疗', value: 'healthcare' },
  { label: '教育', value: 'education' },
  { label: '电信', value: 'telecom' },
  { label: '通用', value: 'general' },
];

const LANGUAGE_OPTIONS = [
  { label: '中文', value: 'zh' },
  { label: 'English', value: 'en' },
  { label: '日本語', value: 'ja' },
  { label: '한국어', value: 'ko' },
];

const ACCEPT_FORMATS = '.pdf,.csv,.txt';

const AGENT_ROLES = ['customer', 'translate', 'lead', 'triage'] as const;

function mockGenerateSouls(tenantId: string, _brandName: string, _industry: string): Promise<GenerationResult> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const souls: GenerationResult['souls'] = {};
      for (const role of AGENT_ROLES) {
        souls[role] = {
          role,
          kbHitCount: Math.floor(Math.random() * 10) + 3,
          mode: 'ai',
          warnings: [],
        };
      }
      resolve({
        tenantId,
        souls,
        totalKbHits: Object.values(souls).reduce((sum, s) => sum + s.kbHitCount, 0),
        mode: 'ai',
        warnings: [],
      });
    }, 1500);
  });
}

interface MaterialUploadStepProps {
  tenantId: string;
  onGenerated?: () => void;
}

export function MaterialUploadStep({ tenantId, onGenerated }: MaterialUploadStepProps) {
  const { wizardFormData, setWizardFormData, generating, setGenerating, generationResult, setGenerationResult } =
    useAdminStore();
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  const brandName = wizardFormData.brandName;

  const handleGenerate = async () => {
    if (!brandName.trim()) return;
    setGenerating(true);
    try {
      const result = await mockGenerateSouls(tenantId, brandName, wizardFormData.industry);
      setGenerationResult(result);
      onGenerated?.();
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div data-testid="material-upload-step">
      <Typography.Title level={5}>资料上传</Typography.Title>
      <Form layout="vertical" style={{ maxWidth: 600 }}>
        <Form.Item label="公司官网" help="选填，用于抓取产品信息">
          <Input
            placeholder="https://example.com"
            value={wizardFormData.websiteUrl}
            onChange={(e) => setWizardFormData({ websiteUrl: e.target.value })}
          />
        </Form.Item>

        <Form.Item label="品牌名称" required>
          <Input
            placeholder="请输入品牌名称"
            data-testid="input-brand-name"
            aria-label="品牌名称"
            value={brandName}
            onChange={(e) => setWizardFormData({ brandName: e.target.value })}
          />
        </Form.Item>

        <Form.Item label="行业">
          <Select
            data-testid="select-industry"
            placeholder="选择行业"
            value={wizardFormData.industry}
            onChange={(v) => setWizardFormData({ industry: v })}
            options={INDUSTRY_OPTIONS}
            style={{ width: '100%' }}
          />
        </Form.Item>

        <Form.Item label="支持语言">
          <Select
            mode="multiple"
            data-testid="select-languages"
            value={wizardFormData.languages}
            onChange={(v) => setWizardFormData({ languages: v })}
            options={LANGUAGE_OPTIONS}
          />
        </Form.Item>

        <Form.Item label="产品资料">
          <div data-testid="upload-area">
            <Upload.Dragger
              accept={ACCEPT_FORMATS}
              multiple
              fileList={fileList}
              beforeUpload={(file) => {
                setFileList((prev) => [...prev, file]);
                return false;
              }}
              onRemove={(file) => {
                setFileList((prev) => prev.filter((f) => f.uid !== file.uid));
              }}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽文件上传</p>
              <p className="ant-upload-hint">支持 PDF、CSV、TXT 格式</p>
            </Upload.Dragger>
          </div>
        </Form.Item>

        <Form.Item label="额外备注">
          <Input.TextArea
            rows={3}
            placeholder="希望 Agent 注意的事项（选填）"
            value={wizardFormData.extraContext}
            onChange={(e) => setWizardFormData({ extraContext: e.target.value })}
          />
        </Form.Item>

        <Form.Item>
          <Button
            type="primary"
            data-testid="btn-generate"
            disabled={!brandName.trim() || generating}
            onClick={handleGenerate}
            loading={generating}
          >
            生成 Agent
          </Button>
        </Form.Item>
      </Form>

      {generating && (
        <div data-testid="generating-indicator">
          <Spin tip="正在生成 Agent soul.md..." />
        </div>
      )}

      {generationResult && !generating && (
        <div data-testid="generation-result">
          <Typography.Title level={5} style={{ marginTop: 16 }}>生成结果</Typography.Title>
          <Space wrap>
            {AGENT_ROLES.map((role) => {
              const soul = generationResult.souls[role];
              if (!soul) return null;
              return (
                <Card key={role} size="small" style={{ width: 200 }} data-testid={`role-card-${role}`}>
                  <Typography.Text strong>{role}</Typography.Text>
                  <div style={{ marginTop: 8 }}>
                    <Tag
                      color={soul.mode === 'ai' ? 'green' : 'orange'}
                      icon={soul.mode === 'ai' ? <CheckCircleOutlined /> : <WarningOutlined />}
                    >
                      {soul.mode === 'ai' ? 'AI 生成' : '模板生成'}
                    </Tag>
                  </div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    KB 命中: {soul.kbHitCount}
                  </Typography.Text>
                  {soul.warnings.length > 0 && (
                    <Alert type="warning" message={soul.warnings.join('; ')} style={{ marginTop: 8 }} />
                  )}
                </Card>
              );
            })}
          </Space>
          {generationResult.warnings.length > 0 && (
            <Alert
              type="warning"
              message="生成警告"
              description={generationResult.warnings.join('\n')}
              style={{ marginTop: 16 }}
            />
          )}
        </div>
      )}

      <div style={{ marginTop: 24 }}>
        <Button
          type="primary"
          data-testid="btn-next-step"
          disabled={!generationResult}
        >
          下一步
        </Button>
      </div>
    </div>
  );
}

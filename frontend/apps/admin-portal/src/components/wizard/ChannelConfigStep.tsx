import { useState } from 'react';
import { Button, Checkbox, Space, Typography } from 'antd';
import { CopyOutlined } from '@ant-design/icons';

const channelOptions = [
  { label: 'Web 在线客服', value: 'web' },
  { label: '飞书 IM', value: 'feishu', disabled: true },
];

interface ChannelConfigStepProps {
  tenantId: string;
}

export function ChannelConfigStep({ tenantId }: ChannelConfigStepProps) {
  const [selectedChannels, setSelectedChannels] = useState<string[]>(['web']);
  const [generatedUrl, setGeneratedUrl] = useState<string | null>(null);

  const handleGenerate = () => {
    setGeneratedUrl(`https://${tenantId}.autoservice.ai/chat`);
  };

  return (
    <div data-testid="channel-config-step">
      <Typography.Title level={5}>渠道配置</Typography.Title>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Checkbox.Group
          data-testid="channel-checkboxes"
          options={channelOptions}
          value={selectedChannels}
          onChange={(values) => setSelectedChannels(values as string[])}
        />
        <Button
          type="primary"
          data-testid="btn-generate-url"
          disabled={selectedChannels.length === 0}
          onClick={handleGenerate}
        >
          生成链接
        </Button>
        {generatedUrl && (
          <Typography.Text data-testid="generated-url" copyable={{ icon: <CopyOutlined /> }}>
            {generatedUrl}
          </Typography.Text>
        )}
      </Space>
    </div>
  );
}

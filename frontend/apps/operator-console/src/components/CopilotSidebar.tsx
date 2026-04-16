import { useState } from 'react';
import { Button, Input, Layout, List, Typography } from 'antd';
import { CloseOutlined, SendOutlined } from '@ant-design/icons';
import { useOperatorStore, type CopilotMessage } from '../store/operatorStore';
import type { Envelope } from '@autoservice/ws-client';

const { Sider } = Layout;

interface CopilotSidebarProps {
  send: (frame: Envelope) => void;
}

export function CopilotSidebar({ send }: CopilotSidebarProps) {
  const activeCopilotConvId = useOperatorStore((s) => s.activeCopilotConvId);
  const copilotMessages = useOperatorStore((s) => s.copilotMessages);
  const closeCopilot = useOperatorStore((s) => s.closeCopilot);
  const addCopilotMessage = useOperatorStore((s) => s.addCopilotMessage);

  const conversations = useOperatorStore((s) => s.conversations);
  const [inputText, setInputText] = useState('');

  if (!activeCopilotConvId) return null;

  const messages: CopilotMessage[] = copilotMessages[activeCopilotConvId] ?? [];
  const conv = conversations[activeCopilotConvId];
  const isTakeover = conv?.mode === 'takeover';

  const handleSend = () => {
    const text = inputText.trim();
    if (!text || !activeCopilotConvId) return;

    const id = crypto.randomUUID();
    const ts = new Date().toISOString();

    addCopilotMessage(activeCopilotConvId, {
      id,
      text,
      sender: 'operator',
      ts,
    });

    send({
      v: 1,
      type: isTakeover ? 'send_message' : 'operator_message',
      id,
      ts,
      payload: {
        conversation_id: activeCopilotConvId,
        text,
        ...(isTakeover ? { visible_to_customer: true } : {}),
      },
    } as Envelope);

    setInputText('');
  };

  return (
    <Sider
      width={360}
      theme="light"
      data-testid="copilot-sidebar"
      style={{ borderLeft: '1px solid #f0f0f0', height: '100vh', display: 'flex', flexDirection: 'column' }}
    >
      <div style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #f0f0f0' }}>
        <Typography.Text strong data-testid="copilot-title">
          {isTakeover ? '正式回复' : 'Copilot'}
        </Typography.Text>
        {isTakeover && <Typography.Text type="danger" style={{ fontSize: 11, marginLeft: 8 }} data-testid="takeover-indicator">TAKEOVER</Typography.Text>}
        <Button
          type="text"
          size="small"
          icon={<CloseOutlined />}
          data-testid="copilot-close"
          onClick={closeCopilot}
        />
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        <List
          dataSource={messages}
          renderItem={(msg) => (
            <List.Item key={msg.id} data-testid={`copilot-message-${msg.id}`} style={{ padding: '4px 0' }}>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                  {msg.sender} - {msg.ts}
                </Typography.Text>
                <div>
                  <Typography.Text>{msg.text}</Typography.Text>
                </div>
              </div>
            </List.Item>
          )}
        />
      </div>
      <div style={{ padding: 16, borderTop: '1px solid #f0f0f0', display: 'flex', gap: 8 }}>
        <Input
          data-testid="copilot-input"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onPressEnter={handleSend}
          placeholder={isTakeover ? '正式回复客户...' : '输入建议...'}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          data-testid="copilot-send"
          onClick={handleSend}
        />
      </div>
    </Sider>
  );
}

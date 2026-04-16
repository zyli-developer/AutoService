import { useEffect } from 'react';
import { Button, Card, Progress, Space, Spin, Tag, Typography } from 'antd';
import { CheckCircleOutlined, WarningOutlined } from '@ant-design/icons';
import { useAdminStore } from '../../store/adminStore';
import type { SimDialogUI, SimTurnUI } from '../../store/adminStore';

const PERSONAS = [
  { id: 'angry-refund', name_zh: '愤怒退款客户', traits: ['情绪激动', '用词尖锐', '要求立即处理'], communication_style: 'aggressive' },
  { id: 'price-sensitive', name_zh: '价格敏感客户', traits: ['反复询问价格', '比较竞品', '要求折扣'], communication_style: 'cautious' },
  { id: 'non-native-speaker', name_zh: '非母语客户', traits: ['语法不规范', '用词简单', '偶有拼写错误'], communication_style: 'hesitant' },
  { id: 'tech-illiterate', name_zh: '技术小白客户', traits: ['描述模糊', '不懂术语', '需要逐步引导'], communication_style: 'confused' },
  { id: 'repeat-customer', name_zh: '老客户', traits: ['熟悉产品', '提及历史订单', '期望优先处理'], communication_style: 'familiar' },
  { id: 'cross-border', name_zh: '跨境客户', traits: ['关注物流时效', '询问关税', '时区差异'], communication_style: 'formal' },
] as const;

const SCENARIOS = [
  { id: 'general-greeting', name_zh: '通用问候', intent: 'general_question', keywords: ['你好', '在吗'], trap_question: '你们公司在哪个城市？', degraded: false },
  { id: 'basic-inquiry', name_zh: '基本咨询', intent: 'product_inquiry', keywords: ['怎么用', '功能'], trap_question: '你们支持哪些支付方式？', degraded: false },
  { id: 'complaint-generic', name_zh: '通用投诉', intent: 'complaint', keywords: ['投诉', '不满'], trap_question: '我要投诉到消费者协会，你们的投诉热线是多少？', degraded: false },
  { id: 'purchase-generic', name_zh: '通用购买意向', intent: 'purchase_intent', keywords: ['价格', '购买'], trap_question: '你们有没有教育优惠？', degraded: false },
  { id: 'language-barrier', name_zh: '语言障碍', intent: 'language_barrier', keywords: [], trap_question: 'Can you speak English?', degraded: true },
] as const;

function generateMockTurns(scenarioIdx: number, hasTrap: boolean): SimTurnUI[] {
  const turnTemplates = [
    ['你好，我想咨询一下', '您好！很高兴为您服务，请问有什么可以帮到您？'],
    ['这个产品怎么使用？', '这款产品的使用方法很简单，首先...'],
    ['价格是多少？', '目前的价格方案如下...'],
    ['我要投诉！', '非常抱歉给您带来不好的体验，请问具体是什么问题呢？'],
  ];
  const template = turnTemplates[scenarioIdx % turnTemplates.length];
  const turns: SimTurnUI[] = [
    { role: 'customer', content: template[0], metadata: {} },
    { role: 'agent', content: template[1], metadata: {} },
    { role: 'customer', content: '还有一个问题', metadata: {} },
    { role: 'agent', content: '请说，我在听。', metadata: {} },
  ];
  if (hasTrap) {
    turns.push({ role: 'customer', content: SCENARIOS[scenarioIdx % SCENARIOS.length].trap_question, metadata: { is_trap: true } });
    turns.push({ role: 'agent', content: '这个问题我需要确认一下，请稍等。', metadata: {} });
  }
  return turns;
}

function mockGenerateDialogs(_tenantId: string): Promise<SimDialogUI[]> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const dialogs: SimDialogUI[] = [];
      for (let i = 0; i < 12; i++) {
        const persona = PERSONAS[i % PERSONAS.length];
        const scenario = SCENARIOS[i % SCENARIOS.length];
        const hasTrap = i < 2;
        dialogs.push({
          id: `dialog-${String(i + 1).padStart(3, '0')}`,
          scenario: { id: scenario.id, name_zh: scenario.name_zh, intent: scenario.intent, keywords: [...scenario.keywords], trap_question: scenario.trap_question, degraded: scenario.degraded || false },
          persona: { id: persona.id, name_zh: persona.name_zh, traits: [...persona.traits], communication_style: persona.communication_style },
          turns: generateMockTurns(i, hasTrap),
          language: 'zh',
          review_status: 'pending',
        });
      }
      resolve(dialogs);
    }, 1500);
  });
}

const STYLE_LABELS: Record<string, string> = {
  aggressive: '激进',
  cautious: '谨慎',
  hesitant: '犹豫',
  confused: '困惑',
  familiar: '熟络',
  formal: '正式',
};

interface VirtualRehearsalStepProps {
  tenantId: string;
}

export function VirtualRehearsalStep({ tenantId }: VirtualRehearsalStepProps) {
  const {
    rehearsalDialogs,
    rehearsalLoading,
    setRehearsalDialogs,
    setRehearsalLoading,
    updateDialogReviewStatus,
  } = useAdminStore();

  const reviewed = rehearsalDialogs.filter((d) => d.review_status !== 'pending').length;
  const total = rehearsalDialogs.length;
  const allReviewed = total > 0 && reviewed === total;

  const handleStartRehearsal = async () => {
    setRehearsalLoading(true);
    try {
      const dialogs = await mockGenerateDialogs(tenantId);
      setRehearsalDialogs(dialogs);
    } finally {
      setRehearsalLoading(false);
    }
  };

  useEffect(() => {
    if (rehearsalDialogs.length === 0 && !rehearsalLoading) {
      // Don't auto-trigger — let user click the button
    }
  }, [rehearsalDialogs.length, rehearsalLoading]);

  return (
    <div data-testid="virtual-rehearsal-step">
      <Typography.Title level={5}>虚拟客户预演</Typography.Title>
      <Typography.Paragraph type="secondary">
        系统将生成模拟客户对话，请逐条审阅并标记结果。
      </Typography.Paragraph>

      {rehearsalDialogs.length === 0 && !rehearsalLoading && (
        <Button
          type="primary"
          data-testid="btn-start-rehearsal"
          onClick={handleStartRehearsal}
        >
          开始预演
        </Button>
      )}

      {rehearsalLoading && (
        <div data-testid="rehearsal-loading">
          <Spin tip="正在生成虚拟对话..." />
        </div>
      )}

      {rehearsalDialogs.length > 0 && !rehearsalLoading && (
        <>
          <div data-testid="rehearsal-progress" style={{ marginBottom: 16 }}>
            <Progress
              percent={Math.round((reviewed / total) * 100)}
              format={() => `${reviewed}/${total} 已审阅`}
            />
          </div>

          <div data-testid="dialog-list">
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              {rehearsalDialogs.map((dialog) => (
                <Card
                  key={dialog.id}
                  size="small"
                  data-testid={`dialog-card-${dialog.id}`}
                  title={
                    <Space>
                      <span>{dialog.scenario.name_zh}</span>
                      <Tag>{dialog.persona.name_zh}</Tag>
                      <Tag color="blue">{STYLE_LABELS[dialog.persona.communication_style] || dialog.persona.communication_style}</Tag>
                      {dialog.scenario.degraded && (
                        <Tag color="orange" data-testid={`degraded-tag-${dialog.id}`}>降级场景</Tag>
                      )}
                    </Space>
                  }
                  extra={
                    <Space>
                      {dialog.review_status === 'approved' && (
                        <Tag color="green" icon={<CheckCircleOutlined />}>已通过</Tag>
                      )}
                      {dialog.review_status === 'flagged' && (
                        <Tag color="orange" icon={<WarningOutlined />}>已标记</Tag>
                      )}
                      {dialog.review_status === 'pending' && (
                        <>
                          <Button
                            size="small"
                            type="primary"
                            data-testid={`btn-approve-${dialog.id}`}
                            icon={<CheckCircleOutlined />}
                            onClick={() => updateDialogReviewStatus(dialog.id, 'approved')}
                          >
                            通过
                          </Button>
                          <Button
                            size="small"
                            danger
                            data-testid={`btn-flag-${dialog.id}`}
                            icon={<WarningOutlined />}
                            onClick={() => updateDialogReviewStatus(dialog.id, 'flagged')}
                          >
                            标记
                          </Button>
                        </>
                      )}
                    </Space>
                  }
                >
                  <div data-testid={`dialog-turns-${dialog.id}`}>
                    {dialog.turns.map((turn, idx) => (
                      <div
                        key={idx}
                        style={{
                          display: 'flex',
                          justifyContent: turn.role === 'customer' ? 'flex-start' : 'flex-end',
                          marginBottom: 8,
                        }}
                      >
                        <div
                          style={{
                            maxWidth: '70%',
                            padding: '8px 12px',
                            borderRadius: 8,
                            background: turn.role === 'customer' ? '#f0f0f0' : '#e6f7ff',
                          }}
                        >
                          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                            {turn.role === 'customer' ? '客户' : 'Agent'}
                          </Typography.Text>
                          <div>{turn.content}</div>
                          {Boolean(turn.metadata?.is_trap) && (
                            <Tag color="volcano" style={{ marginTop: 4 }} data-testid={`trap-tag-${dialog.id}`}>
                              陷阱题
                            </Tag>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              ))}
            </Space>
          </div>
        </>
      )}

      <div style={{ marginTop: 24 }}>
        <Button
          type="primary"
          data-testid="btn-next-step"
          disabled={!allReviewed}
        >
          下一步
        </Button>
      </div>
    </div>
  );
}

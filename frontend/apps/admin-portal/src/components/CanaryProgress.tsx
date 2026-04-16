import { Card, Progress, Space, Steps, Table, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, SyncOutlined } from '@ant-design/icons';
import { useAdminStore } from '../store/adminStore';
import type { CanaryStage } from '../store/adminStore';

const STAGE_LABELS: Record<CanaryStage, string> = {
  disabled: '未启动',
  stage_5: '5%',
  stage_25: '25%',
  stage_100: '100%',
};

const STAGE_ORDER: CanaryStage[] = ['disabled', 'stage_5', 'stage_25', 'stage_100'];

const columns = [
  {
    title: '指标',
    dataIndex: 'name',
    key: 'name',
  },
  {
    title: '基线',
    dataIndex: 'baseline',
    key: 'baseline',
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '当前',
    dataIndex: 'current',
    key: 'current',
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '状态',
    dataIndex: 'breached',
    key: 'breached',
    render: (breached: boolean) =>
      breached ? (
        <Tag color="red" icon={<CloseCircleOutlined />} data-testid="metric-breached">超阈值</Tag>
      ) : (
        <Tag color="green" icon={<CheckCircleOutlined />} data-testid="metric-ok">正常</Tag>
      ),
  },
];

const METRIC_LABELS: Record<string, string> = {
  csat: 'CSAT 评分',
  resolution_rate: '升级→结案率',
  digest_rate: '对话摘要率',
  accept_wait_ms: 'P95 响应时间(ms)',
  complaint_rate: '投诉率',
};

export function CanaryProgress() {
  const canaryState = useAdminStore((s) => s.canaryState);

  if (!canaryState) {
    return (
      <Card data-testid="canary-progress" size="small">
        <Typography.Text type="secondary" data-testid="canary-empty">暂无灰度发布</Typography.Text>
      </Card>
    );
  }

  const currentStepIdx = STAGE_ORDER.indexOf(canaryState.stage);
  const breachedCount = canaryState.metrics.filter((m) => m.breached).length;

  const tableData = canaryState.metrics.map((m) => ({
    ...m,
    key: m.name,
    name: METRIC_LABELS[m.name] || m.name,
  }));

  return (
    <Card data-testid="canary-progress" size="small">
      <Typography.Title level={5}>灰度发布进度</Typography.Title>

      <Steps
        current={currentStepIdx}
        data-testid="canary-steps"
        size="small"
        style={{ marginBottom: 16 }}
        items={STAGE_ORDER.map((stage) => ({
          title: STAGE_LABELS[stage],
        }))}
      />

      <Space style={{ marginBottom: 16 }}>
        <Progress
          type="circle"
          percent={canaryState.percentage}
          size={80}
          data-testid="canary-percentage"
          status={canaryState.rolledBack ? 'exception' : undefined}
        />
        <div>
          <div>
            <Tag
              color={canaryState.rolledBack ? 'red' : 'blue'}
              icon={canaryState.rolledBack ? <CloseCircleOutlined /> : <SyncOutlined />}
              data-testid="canary-status-tag"
            >
              {canaryState.rolledBack ? '已回滚' : `灰度中 (${canaryState.percentage}%)`}
            </Tag>
          </div>
          {breachedCount > 0 && (
            <Tag color="red" style={{ marginTop: 4 }} data-testid="breach-count">
              {breachedCount} 项指标超阈值
            </Tag>
          )}
        </div>
      </Space>

      <Table
        dataSource={tableData}
        columns={columns}
        pagination={false}
        size="small"
        data-testid="canary-metrics-table"
      />
    </Card>
  );
}

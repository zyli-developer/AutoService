# NFR-4: 同主机部署约束策略

> channel-server 与 bridges 必须共享网络命名空间。违规将导致 RTT 10x 劣化。

## 约束内容

| 组件 | 要求 | 实现方式 |
|------|------|---------|
| bridges | 与 channel-server 同网络栈 | `network_mode: "service:channel-server"` |
| channel-server | 所有 bridge 流量走 localhost | Docker 网络命名空间共享 |

## 为什么

v1.1 架构引入 3-4 跳：`bridge → Bridge API → channel-server → IRC`。
同主机 RTT: 10-30ms（SLA 安全）；跨主机 RTT: 100-300ms（SLA 不可接受）。

## 防护层级

### Layer 1: CI 静态校验

`deploy/check-colocation.sh` 在 CI 中自动执行，检查：
- `docker-compose.tmpl.yaml` 中 bridges 的 `network_mode` 值
- 所有 `deploy/tenants/*/docker-compose.yml` 渲染产物

失败则阻断 PR 合并。

### Layer 2: CODEOWNERS 双人审批

`.github/CODEOWNERS` 要求修改以下文件时需 `@product-owner` + `@sre-lead` 双人 approve：
- `deploy/docker-compose.tmpl.yaml`
- `deploy/tenants/`

## 豁免流程

如确需跨主机部署（如压力测试、灾备演练）：

1. 在 PR 描述中注明原因和预期 RTT 影响
2. 获得 `@product-owner` + `@sre-lead` 双人 approve
3. 部署后 24h 内验证 P95 RTT < 100ms，否则回滚
4. 临时豁免最长 7 天，到期自动恢复

## 检查命令

```bash
# 检查模板 + 所有租户
deploy/check-colocation.sh

# 检查单个文件
deploy/check-colocation.sh --file deploy/tenants/demo/docker-compose.yml
```

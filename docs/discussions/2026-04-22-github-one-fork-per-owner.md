# GitHub "一 owner 一 fork" 行为考证

**日期**：2026-04-22
**起因**：冒烟测试 M2 §3.4 `GitHubApiForkCreator` 时观察到，`gh repo fork --fork-name=B` 在已有 fork 的场景下**重命名**既有 fork，而不是新建第二个。
**影响**：M2 spec "一 tenant 一 fork" 模型在单 GitHub 账号下不成立。
**本文作用**：为后续架构选型提供可引用的证据基础；日后被挑战时直接贴此文。

---

## 1. 精确问题

能否在同一 GitHub owner（个人账号 / org / Enterprise owner）下，针对同一个 upstream 仓库持有**多个** fork？

## 2. 结论（先给精简版）

**不能，在 GitHub 当前的 fork 网络架构下每 owner 对每 upstream 只能持有 1 个 fork 节点。** 这是平台**事实上的行为**（by fork 网络数据模型），**不是明文文档化的规则**——即 `docs.github.com` 上找不到一句"每用户最多 1 个 fork"的直接声明。

跨 owner（例如不同 org）可以叠加。

## 3. 证据

### 3.1 官方文档页（反向证据）

[About permissions and visibility of forks — GitHub Docs](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/about-permissions-and-visibility-of-forks)

**检索结论**：此页**不包含**任何"一 owner 一 fork"的直接声明。讨论范围仅限权限、可见性、安全性，没有数量限制的章节。

所以引用"GitHub 官方文档规定"是**过头的说法**——准确的说法是"平台行为如此，未见文档反驳，也未见文档明说"。

### 3.2 GitHub CLI 官方 issue（行为复现）

[cli/cli#6329 — "Forking someone else's repo while changing its name instead renames my existing repo"](https://github.com/cli/cli/issues/6329) · **OPEN since 2022**

用户 `ChaiTRex` 报告与我们一致的观察：

> I have a repository called `ChaiTRex/rust` that is a fork of `rust-lang/rust`. […] When I told `gh` to do that [make a second fork with a new name], it instead didn't do any forking at all and renamed my repository.

使用的命令：
```
gh repo fork rust-lang/rust --fork-name rust-pureiterator --clone --remote-name github
```

结果：`ChaiTRex/rust` 被**重命名**为 `ChaiTRex/rust-pureiterator`，**没有产生新的 fork**。

意义：gh 维护团队 2+ 年未改此行为，说明这是 GitHub API `POST /repos/{owner}/{repo}/forks` 的**已知且稳定**的语义。

### 3.3 社区讨论（官方员工未在此层面表态）

以下三条 discussion 都在追同一个问题，**均无 GitHub staff 的官方答复**——回答全部来自社区用户：

- [Forking a repo twice · discussion #23095](https://github.com/orgs/community/discussions/23095)
- [Can't create 2 forks of a repo · discussion #79137](https://github.com/orgs/community/discussions/79137)
- [How to convert an existing repo into a fork of another (same owner) · discussion #167393](https://github.com/orgs/community/discussions/167393)

共性答复（社区答案，非官方）：

> "Create an Org, even if you don't have members, and fork it there — that way you have two existing forks from the same source."

### 3.4 实证 API 数据

2026-04-22 对 `ezagent42/AutoService` 的 fork 网络查询：

```
$ gh api repos/ezagent42/AutoService/forks | jq '.[] | {full_name}'
gagameow:        1 fork — AutoService-tenant_bca09a90
zyli-developer:  1 fork — AutoService
ezagent42:       1 fork — AutoService-Cinnox        # 自己 fork 自己（同 owner 不同仓名不同策略）
```

3 个 distinct owner × 各 1 fork = 总 3 fork。没有任何一个 owner 持有 2 个。

### 3.5 冒烟测试日志（本项目）

- 2026-04-22 06:28 UTC：pytest 跑 `test_publish_happy_path` 用 `tenant_id=tenant_http`，gh fork 创建了 `gagameow/AutoService-tenant_http`。
- 2026-04-22 06:32 UTC：smoke test 用 `tenant_id=tenant_bca09a90` 再跑 `gh repo fork --fork-name=AutoService-tenant_bca09a90`：
  - **新 fork 没有被创建**
  - `gagameow/AutoService-tenant_http` 被**重命名**为 `gagameow/AutoService-tenant_bca09a90`
  - 旧的 `Install tenant tenant_http` commit 保留在新 fork 的历史里
  - `gh repo view gagameow/AutoService-tenant_http` 返回 `{"name":"AutoService-tenant_bca09a90"}`——即 GitHub 内部做了 repo 重定向

唯一存活的 fork：<https://github.com/gagameow/AutoService-tenant_bca09a90>。commit 历史：

```
d672ec43  2026-04-22T06:32:52Z  Install tenant tenant_bca09a90   ← smoke test
4d40d5f6  2026-04-22T06:28:20Z  Install tenant tenant_http       ← pytest 意外落地
```

## 4. 对 AutoService M2 §3.4 的影响

`autoservice/publish.py::GitHubApiForkCreator` 的设计前提是"一 tenant → 一 GitHub fork"。这个假设在**单 admin 账号**下**不成立**：

- 第 2 次 publish 会把第 1 次租户的 fork 重命名
- 第 2 次租户的仓库里会带着第 1 次租户的 commit 历史
- 跨租户隔离失败（代码 + 数据混在一起）

**不是"多跑几次就好"，是架构层面的问题。**

## 5. 可选路径（架构决策用）

| 方案 | 机制 | 优点 | 代价 |
|---|---|---|---|
| **A. 多 org 强制** | 每租户自带 org owner；publish 时 `gh repo fork --org=<tenant-org>` | 保留 fork 关系 + 现有 `auto-sync-pr.yml` 逻辑不变 | 运维要管 N 个 org 的 billing / SSO / 成员；N 增长即成本增长 |
| **B. Template repo** | upstream 标为 template；publish 改调 `gh repo create --template=<upstream> <new-repo>` | 每次产出**独立**新仓；天然支持"一模板多实例"；`gh repo sync` 官方支持上游同步 | 丢失 fork 元数据（无 Compare & PR 回上游）；`auto-sync-pr.yml` 的 fast-forward merge 需改写；cinnox 这种要回贡的租户不适用 |
| **C. 混合** | 默认 B（多数租户）；`--fork-creator=github_fork` 选项给少数要回贡的租户 | 兼顾两类诉求 | 代码复杂；spec + runbook 要讲清何时用哪个 |
| **D. 暂不自动化** | 保留 `LocalTarballForkCreator`（M1 runbook）；`GitHubApiForkCreator.create()` 留着但 spec 明文"生产环境要求每租户独立 org" | 零代码改动，回到 M1 假设 | 自动化端到端声称"通"变成"通但有场景限制"——对单账号 demo 不适用 |

**个人倾向 B**：`gh repo create --template` 是 GitHub 为"一模板多实例"场景设计的原生机制，语义对齐"租户实例化"；社区/官方都有 `gh repo sync` 作为上游同步的配套能力。但这是**架构决策**，应由产品 + 架构层面共同决定，不由 implementer 单方拍板。

## 6. 行动项

- [ ] 本文作为 M2 §3.4 的附注，被 spec 引用
- [ ] 架构层面决定走 A / B / C / D；立 issue 追踪
- [ ] `GitHubApiForkCreator` 当前实装（feat 分支 `feat/publish-fork-creator-wiring`）**不删**——选项 A 下它是可用资产，选项 C 下它是"fork 路径"的实现
- [ ] 若选 B：新立 task 设计 `GitHubTemplateCreator`（平行于 `GitHubApiForkCreator`）+ 修 `auto-sync-pr.yml`

## 附录 A · 查询命令

复现证据的命令（任何时间重跑都是权威）：

```bash
# 对 upstream 的 fork 网络 owner 分布
gh api "repos/ezagent42/AutoService/forks?per_page=100" \
  | jq '[.[] | .owner.login] | group_by(.) | map({owner: .[0], count: length})'

# 用户账号当前持有的所有 fork
gh repo list <owner> --json name,isFork,parent --limit 100

# 验证已知行为（谨慎：会产生副作用）
gh repo fork <upstream> --fork-name=<new-name> --clone=false
# 若目标账号已有 upstream 的 fork → 该 fork 会被重命名
```

## 附录 B · 相关 commit

`feat/publish-fork-creator-wiring` 分支上暴露此问题的三个 commit：

- `8457082` — `GitHubApiForkCreator.create()` + 路由选择器
- `13bbb04` — code review 修复（tarfile filter、tenant_id 验证、temp 清理）
- `6cdaabc` — 冒烟测试修复（git add -f、pytest test isolation）+ commit message 里首次记录此限制

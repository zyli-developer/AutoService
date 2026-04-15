# /discuss 指令设计文档 — 动态指令注册系统

> 日期: 2026-04-14
> 作者: huangjiajia
> 状态: Draft v3
> 层级: L2 (channels/feishu)

## 1. 目标

在飞书 IM 中实现 `/discuss` 指令体系，核心能力是**动态创建指令并映射到已有 skill**。用户通过 `/discuss create cmd` 在运行时注册新的飞书斜杠指令，注册后即可在会话中直接使用新指令。

### 用例示例

```ini
管理员: /discuss create cmd /review evaluate "文档评审快捷入口"
系统:   已注册指令 /review → evaluate skill

用户:   /review docs/plans/xxx.md
系统:   (触发 evaluate skill，等同于 /evaluate @docs/plans/xxx.md)
```

## 2. 现有架构分析

### 2.1 指令分发流程

```ini
飞书用户消息
  ↓
channel_server.py: on_message()
  ├─ 硬编码指令: /improve, /production → 模式切换 (L555-588)
  ├─ 管理群 /xxx: _handle_admin_message() → /help, /status, /inject, /explain
  └─ 普通消息: route_message() → channel.py → Claude Code
       ↓
  Claude Code 读 channel-instructions.md
       ↓ 按 runtime_mode 路由
  ├─ production + sales → /cinnox-demo skill
  ├─ production + support → /customer-service skill
  ├─ improve → /improve skill
  └─ explain → /explain skill
```

### 2.2 Skill 全景 — 三个来源

Skill 分布在三个位置，channel_server 需要能发现所有来源:

| 来源 | 路径 | 数量 | 已关联到飞书指令? |
|---|---|---|---|
| **项目自有** | `skills/` | 9 | 部分 (4/9 通过 channel-instructions 硬编码) |
| **官方内置** | `.claude/skills/skills/` (symlink) | 17 | 无 |
| **插件 (dev-loop)** | `~/.claude/plugins/cache/ezagent42/.../skills/` | 7 | 无 |

#### 项目自有 Skill (skills/)

| Skill 名 | 子命令 | 飞书关联状态 |
|---|---|---|
| customer-service | create/read/update/delete/list/call | **已关联** (production+support) |
| cinnox-demo | (会话式) | **已关联** (production+sales) |
| improve | (自由文本) | **已关联** (/improve 模式切换) |
| explain | (query) | **已关联** (/explain 管理群指令) |
| marketing | create/read/update/delete/list/call | 未关联 |
| evaluate | @path/list/report/sync/synthesis/status | 未关联 |
| knowledge-base | build/search/status/migrate | 未关联 |
| sales-demo | (会话式) | 未关联 |
| project-discussion-autoservice | (问答式) | 未关联 |

#### 插件 Skill (dev-loop-skills@ezagent42)

| Skill 名 | 用途 | 飞书关联状态 |
|---|---|---|
| using-dev-loop | Pipeline 路由器 | 未关联 |
| project-builder | 项目引导 (Phase 0) | 未关联 |
| test-plan-generator | 测试计划生成 (Phase 2-3) | 未关联 |
| test-code-writer | 测试代码编写 (Phase 4) | 未关联 |
| test-runner | 测试执行 (Phase 5) | 未关联 |
| feature-eval | 特性评估 (Phase 1,7) | 未关联 |
| artifact-registry | 制品管理 (跨阶段) | 未关联 |

#### 官方内置 Skill (.claude/skills/skills/)

pdf, docx, pptx, xlsx, claude-api, mcp-builder, skill-creator, frontend-design,
web-artifacts-builder, webapp-testing, canvas-design, brand-guidelines, algorithmic-art,
doc-coauthoring, internal-comms, slack-gif-creator, theme-factory — 共 17 个，全部未关联。

### 2.3 Skill 的两种触发机制

1. __通过 runtime_mode 路由__ — channel-instructions.md 中硬编码映射 (improve→/improve, explain→/explain)
2. **通过 Claude Code skill description 匹配** — Claude Code 根据 SKILL.md 的 description 字段自动判断是否触发

新指令系统需要兼容这两种机制。

### 2.4 层级归属分析

| 考量 | 分析 | 结论 |
|---|---|---|
| 代码位置 | 改动集中在 channel_server.py + channel-instructions.md | L2 (channels/feishu) |
| 能力性质 | 指令注册是__框架能力__，非租户定制 | L2 |
| 使用方式 | L3 租户通过飞书指令使用，不需改代码 | L2 提供能力，L3 消费 |
| 数据存储 | registry.yaml 在 .autoservice/ (运行时) | L2/L3 交界 |
| 复用性 | 其他 L2 应用 (如 marketing) 也能用 | L2 |

**结论: 放在 L2 (channels/feishu)**。指令注册机制是 channel adapter 的一部分，L3 租户通过 `/discuss create cmd` 动态使用，不需要 fork 代码。

## 3. 架构设计

### 3.1 核心概念

```ini
/discuss ─── 元指令 (meta-command)
  ├── create cmd  ─── 注册新指令 (映射 skill)
  ├── list cmd    ─── 查看已注册指令
  ├── delete cmd  ─── 删除指令
  ├── discover    ─── 发现所有可用但未关联的 skill
  └── help        ─── 帮助

注册后的指令 ─── 动态指令 (dynamic command)
  例如: /review, /qa, /test-plan
  → 被 channel_server.py 拦截
  → 转换为对应 skill 调用
```

**发现 → 注册 → 使用** 三步工作流:

```ini
Step 1: /discuss discover
  → 扫描三个 skill 来源，列出所有未被映射的 skill
  → 按来源分组显示

Step 2: /discuss create cmd /test-plan test-plan-generator "生成测试计划"
  → 将 test-plan-generator skill 映射到 /test-plan 指令

Step 3: /test-plan 用户登录模块
  → 触发 test-plan-generator skill
```

### 3.2 系统架构

```ini
┌─────────────────────────────────────────────────────────┐
│ 持久化层: .autoservice/commands/registry.yaml           │
│   存储所有动态注册的指令 → skill 映射                     │
└─────────────────────┬───────────────────────────────────┘
                      │ 启动时加载 / 运行时更新
                      ↓
┌─────────────────────────────────────────────────────────┐
│ 拦截层: channel_server.py                               │
│   1. /discuss xxx → 元指令处理 (create/list/delete)       │
│   2. /<dynamic_cmd> → 查 registry → 构造 skill 调用消息  │
└─────────────────────┬───────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│ 路由层: channel-instructions.md                         │
│   新增 discuss mode: 按 discuss_meta.skill 路由          │
└─────────────────────┬───────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────┐
│ 执行层: 已有 Skills                                     │
│   evaluate, improve, customer-service, ...              │
└─────────────────────────────────────────────────────────┘
```

## 4. 详细设计

### 4.1 指令注册表 (Command Registry)

**存储位置**: `.autoservice/commands/registry.yaml`

```yaml
# .autoservice/commands/registry.yaml
# 动态指令注册表 — 由 /discuss create cmd 写入
version: 1
commands:
  review:
    skill: evaluate
    description: "文档评审快捷入口"
    args_template: "@{args}"          # 参数传递模板
    runtime_mode: discuss          # 注入的 runtime_mode
    created_by: "Allen Woods"
    created_at: "2026-04-14T10:30:00Z"
    
  qa:
    skill: project-discussion-autoservice
    description: "项目知识问答"
    args_template: "{args}"
    runtime_mode: discuss
    created_by: "Allen Woods"
    created_at: "2026-04-14T10:35:00Z"

  kb:
    skill: knowledge-base
    description: "知识库搜索"
    args_template: "search {args}"    # 自动补全子命令
    runtime_mode: discuss
    created_by: "Allen Woods"
    created_at: "2026-04-14T10:40:00Z"
```

**字段说明**:

| 字段 | 必填 | 说明 |
|---|---|---|
| skill | Y | 映射的目标 skill 名，必须存在于 skills/ 目录中 |
| description | Y | 指令用途描述，显示在 /discuss list cmd |
| args_template | N | 参数传递模板，`{args}` 为占位符；默认 `"{args}"` |
| runtime_mode | N | 注入的 runtime_mode；默认 `"discuss"` |
| created_by | N | 注册人 |
| created_at | N | 注册时间 |

### 4.2 元指令: /discuss create cmd

**语法**:

```sh
/discuss create cmd /<name> <skill_name> ["description"]
```

**示例**:

```ini
/discuss create cmd /review evaluate "文档评审快捷入口"
/discuss create cmd /qa project-discussion-autoservice "项目问答"
/discuss create cmd /kb knowledge-base "知识库搜索"
```

**处理流程**:

```python
# channel_server.py 伪代码

def _handle_discuss_create_cmd(self, chat_id, text):
    # 解析: /discuss create cmd /review evaluate "描述"
    match = re.match(
        r'/discuss\s+create\s+cmd\s+/(\w[\w-]*)\s+([\w-]+)\s*(?:"([^"]*)")?',
        text
    )
    if not match:
        return reply(chat_id, USAGE_TEXT)
    
    cmd_name, skill_name, description = match.groups()
    
    # 校验 1: 指令名不能与内置指令冲突
    if cmd_name in RESERVED_COMMANDS:  # improve, production, help, status, ...
        return reply(chat_id, f"/{cmd_name} 是保留指令，不能覆盖")
    
    # 校验 2: skill 必须存在
    if not skill_exists(skill_name):
        return reply(chat_id, f"skill '{skill_name}' 不存在。可用: {available_skills()}")
    
    # 写入 registry
    self._command_registry[cmd_name] = {
        "skill": skill_name,
        "description": description or f"Shortcut for {skill_name}",
        "args_template": "{args}",
        "runtime_mode": "discuss",
        "created_by": display_name,
        "created_at": now_iso(),
    }
    self._save_registry()
    
    reply(chat_id, f"已注册: /{cmd_name} → {skill_name} skill\n{description}")
```

**校验规则**:

| 校验项 | 规则 | 失败消息 |
|---|---|---|
| 指令名格式 | `[\w][\w-]*`, 1-20 字符 | "指令名只允许字母、数字、连字符" |
| 保留字冲突 | 不能是 improve/production/help/status/inject/explain/discuss | "/{name} 是保留指令" |
| Skill 存在性 | 三个来源中任一存在即可 (项目/插件/内置) | "skill 不存在，可用: ... (发送 /discuss discover 查看全部)" |
| 重名处理 | 已存在则覆盖，附带提示 | "已更新: /{name} (原: {old_skill} → 新: {new_skill})" |

### 4.3 元指令: /discuss list cmd

```sh
/discuss list cmd
```

输出:

```ini
已注册指令:

  /review  → evaluate           文档评审快捷入口       (Allen, 04-14)
  /qa      → project-discussion  项目知识问答          (Allen, 04-14)
  /kb      → knowledge-base      知识库搜索            (Allen, 04-14)

共 3 条。使用 /discuss create cmd 注册新指令。
```

### 4.4 元指令: /discuss delete cmd

```sh
/discuss delete cmd /review
```

输出:

```sh
已删除: /review (原映射: evaluate)
```

### 4.5 元指令: /discuss discover

**语法**:

```ini
/discuss discover            # 列出所有未关联 skill
/discuss discover dev-loop   # 按来源过滤
```

**输出示例**:

```ini
可用 Skill (未关联到飞书指令):

[项目自有] skills/
  marketing                  销售系统 (CRUD + call)
  evaluate                   文档评审 (6 子命令)
  knowledge-base             知识库管理
  sales-demo                 通用售前演示
  project-discussion-autoservice  项目知识问答

[插件] dev-loop-skills@ezagent42
  using-dev-loop             Pipeline 路由器
  project-builder            项目引导 (Phase 0)
  test-plan-generator        测试计划生成
  test-code-writer           测试代码编写
  test-runner                测试执行
  feature-eval               特性评估
  artifact-registry          制品管理

[官方内置] .claude/skills/skills/
  pdf                        PDF 处理
  docx                       Word 文档
  ... (共 17 个)

已关联: 4 个 | 未关联: 29 个
使用 /discuss create cmd /<name> <skill> 注册指令。
```

**处理流程**:

```python
def _handle_discuss_discover(self, chat_id, filter_source=None):
    all_skills = self._discover_all_skills()  # { source: [skill_info, ...] }
    mapped = set(e["skill"] for e in self._command_registry.values())
    # 也加上硬编码关联的
    mapped |= {"customer-service", "cinnox-demo", "improve", "explain"}
    
    lines = ["可用 Skill (未关联到飞书指令):\n"]
    for source, skills in all_skills.items():
        if filter_source and filter_source not in source:
            continue
        unmapped = [s for s in skills if s["name"] not in mapped]
        if not unmapped:
            continue
        lines.append(f"[{source}]")
        for s in unmapped:
            lines.append(f"  {s['name']:<30} {s['description'][:30]}")
        lines.append("")
    
    reply(chat_id, "\n".join(lines))
```

### 4.6 多来源 Skill 发现

```python
def _discover_all_skills(self) -> dict[str, list[dict]]:
    """扫描三个来源，返回所有可用 skill。"""
    result = {}
    
    # 来源 1: 项目自有 skills/
    project_skills = self._scan_skills_dir(
        Path(self._project_root) / "skills"
    )
    if project_skills:
        result["项目自有"] = project_skills
    
    # 来源 2: 插件 skill (从 enabledPlugins 配置读取路径)
    plugin_skills = self._scan_plugin_skills()
    if plugin_skills:
        result["插件"] = plugin_skills
    
    # 来源 3: 官方内置 .claude/skills/skills/
    builtin_skills = self._scan_skills_dir(
        Path(self._project_root) / ".claude" / "skills" / "skills"
    )
    if builtin_skills:
        result["官方内置"] = builtin_skills
    
    return result

def _scan_skills_dir(self, skills_dir: Path) -> list[dict]:
    """扫描目录下的 SKILL.md，提取 name + description。"""
    result = []
    if not skills_dir.is_dir():
        return result
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        # 解析 YAML frontmatter
        name, desc = self._parse_skill_frontmatter(skill_md)
        result.append({
            "name": name or d.name,
            "description": desc or "",
            "path": str(d),
            "source_dir": str(skills_dir),
        })
    return result

def _scan_plugin_skills(self) -> list[dict]:
    """从已安装的 Claude Code 插件中发现 skill。"""
    # 读取 .claude/settings.json 的 enabledPlugins
    # 定位插件缓存目录: ~/.claude/plugins/cache/<marketplace>/<plugin>/
    # 扫描其 skills/ 子目录
    cache_base = Path.home() / ".claude" / "plugins" / "cache"
    result = []
    settings = self._load_settings()
    for plugin_key in settings.get("enabledPlugins", {}):
        # plugin_key 格式: "dev-loop-skills@ezagent42"
        name, marketplace = plugin_key.split("@", 1) if "@" in plugin_key else (plugin_key, "")
        plugin_dir = cache_base / marketplace / name
        if not plugin_dir.is_dir():
            continue
        # 查找最新版本目录
        for version_dir in sorted(plugin_dir.iterdir(), reverse=True):
            skills_subdir = version_dir / "skills"
            if skills_subdir.is_dir():
                found = self._scan_skills_dir(skills_subdir)
                for s in found:
                    s["plugin"] = plugin_key
                result.extend(found)
                break  # 只取最新版本
    return result
```

### 4.7 动态指令拦截

当用户发送 `/<name> args...` 时，channel_server.py 检查是否为动态注册指令:

```python
# channel_server.py on_message() 中，在 /improve、/production 判断之后

# 动态指令拦截
elif text_stripped.startswith("/"):
    cmd_parts = text.strip().split(None, 1)
    cmd_name = cmd_parts[0][1:]  # 去掉前缀 /
    cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
    
    if cmd_name in self._command_registry:
        entry = self._command_registry[cmd_name]
        skill_name = entry["skill"]
        runtime_mode = entry.get("runtime_mode", "discuss")
        
        # 应用参数模板
        args_template = entry.get("args_template", "{args}")
        formatted_args = args_template.replace("{args}", cmd_args)
        
        # 构造消息 — 让 Claude Code 知道该调用哪个 skill
        self._chat_modes[chat_id] = runtime_mode
        msg = {
            "type": "message",
            "text": formatted_args,  # skill 看到的是转换后的参数
            "chat_id": chat_id,
            "message_id": msg_id,
            "user": display_name,
            "user_id": sender_id,
            "runtime_mode": runtime_mode,
            "business_mode": "customer_service",
            "discuss_meta": {
                "source_cmd": cmd_name,
                "skill": skill_name,
                "original_text": text,
            },
            "ts": ts,
        }
        loop.call_soon_threadsafe(queue.put_nowait, msg)
        return
```

### 4.6 channel-instructions.md 改动

新增 discuss mode 路由:

```markdown
A dynamically registered command was invoked. Route by `discuss_meta.skill`:
- Read the `discuss_meta.skill` field to determine which skill to invoke
- The message `text` has been pre-formatted by the command registry — use it as the skill input
- Invoke the corresponding skill: `/{discuss_meta.skill}`

Examples:
- discuss_meta.skill = "evaluate" → use /evaluate skill, text contains the document path
- discuss_meta.skill = "knowledge-base" → use /knowledge-base skill, text contains the query
- discuss_meta.skill = "project-discussion-autoservice" → use /project-discussion-autoservice skill
```

### 4.9 Skill 存在性检查 (create cmd 校验用)

```python
def _skill_exists(self, skill_name: str) -> bool:
    """检查 skill 是否存在于任一来源。"""
    all_skills = self._discover_all_skills()
    all_names = set()
    for source_skills in all_skills.values():
        for s in source_skills:
            all_names.add(s["name"])
    return skill_name in all_names

def _available_skill_names(self) -> list[str]:
    """返回所有可用 skill 名称（跨三个来源）。"""
    all_skills = self._discover_all_skills()
    names = set()
    for source_skills in all_skills.values():
        for s in source_skills:
            names.add(s["name"])
    return sorted(names)
```

## 5. 完整拦截优先级

on_message() 中的指令匹配顺序:

```ini
1. /improve        → 切换到 improve 模式 (硬编码)
2. /production     → 切换到 production 模式 (硬编码)
3. /discuss ...    → 元指令处理 (create/list/delete/help)
4. /<dynamic_cmd>  → 查注册表 → 构造 skill 调用
5. (无匹配)        → 普通消息，按 current_mode 路由
```

管理群 `_handle_admin_message()` 中:

```ini
1. /help           → 帮助文本 (硬编码)
2. /status         → 状态 (硬编码)
3. /inject ...     → 注入消息 (硬编码)
4. /explain ...    → explain 模式 (硬编码)
5. /discuss ...    → 元指令处理
6. /<dynamic_cmd>  → 查注册表 → 构造 skill 调用
7. (无匹配)        → 返回未知命令
```

## 6. 消息流示例

### 6.1 注册新指令

```ini
用户:  /discuss create cmd /review evaluate "文档评审"
  ↓
channel_server.py: on_message()
  ↓ 匹配 /discuss
  ↓ 解析: create cmd, name=review, skill=evaluate
  ↓ 校验: "review" 非保留字, evaluate skill 存在
  ↓ 写入 _command_registry + registry.yaml
  ↓ 回复: "已注册: /review → evaluate skill"
  (不进入 Claude Code)
```

### 6.2 使用动态指令

```ini
用户:  /review docs/plans/xxx.md
  ↓
channel_server.py: on_message()
  ↓ 不匹配 /improve, /production, /discuss
  ↓ 查注册表: "review" → { skill: "evaluate", args_template: "@{args}" }
  ↓ 格式化: text = "@docs/plans/xxx.md"
  ↓ 构造 msg: runtime_mode="discuss", discuss_meta.skill="evaluate"
  ↓ route_message()
  ↓
channel.py: inject_message() → MCP notification
  ↓
Claude Code: 读 channel-instructions.md
  ↓ discuss mode → discuss_meta.skill = "evaluate"
  ↓ 触发 /evaluate skill
  ↓ text = "@docs/plans/xxx.md" → evaluate 解析为文档路径
  ↓ 执行评审流程
```

### 6.3 args_template 高级用法

```yaml
# 注册时指定参数模板
/discuss create cmd /kb-search knowledge-base "知识库搜索"

# 自定义模板 (未来扩展，当前版本不暴露此语法)
commands:
  kb-search:
    skill: knowledge-base
    args_template: "search {args} --domain cinnox"
    # 用户输入: /kb-search DID号码
    # skill 收到: "search DID号码 --domain cinnox"
```

## 7. 数据持久化

### 7.1 文件结构

```ini
.autoservice/
  commands/
    registry.yaml       # 指令注册表 (主文件)
```

### 7.2 加载与保存

```python
class ChannelServer:
    def __init__(self, ...):
        ...
        self._command_registry: dict[str, dict] = {}
        self._registry_path = Path(".autoservice/commands/registry.yaml")
        self._load_registry()
    
    def _load_registry(self):
        """启动时从 YAML 加载注册表。"""
        if self._registry_path.exists():
            data = yaml.safe_load(self._registry_path.read_text())
            self._command_registry = data.get("commands", {})
    
    def _save_registry(self):
        """写入 YAML 持久化。"""
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "commands": self._command_registry}
        self._registry_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False)
        )
```

## 8. 保留指令列表

以下指令名不允许被动态注册覆盖:

```python
RESERVED_COMMANDS = {
    "improve", "production", "discuss",
    "help", "status", "inject", "explain",
}
```

## 9. help_text() 更新

在现有 help_text() 中追加:

```ini
/discuss discover [source]                     发现未关联的 skill
/discuss create cmd /<name> <skill> ["desc"]   注册动态指令
/discuss list cmd                              查看已注册指令
/discuss delete cmd /<name>                    删除指令
/discuss help                                  显示帮助
```

## 10. 实现计划

| 步骤 | 文件 | 改动 |
|---|---|---|
| 1 | `channels/feishu/channel_server.py` | 新增 `_command_registry`, `_load/_save_registry()` |
| 2 | `channels/feishu/channel_server.py` | 新增 `_discover_all_skills()`, `_scan_skills_dir()`, `_scan_plugin_skills()` |
| 3 | `channels/feishu/channel_server.py` | on_message() 中新增 `/discuss` 拦截 + 动态指令拦截 |
| 4 | `channels/feishu/channel_server.py` | `_handle_admin_message()` 中新增 `/discuss` + 动态指令支持 |
| 5 | `channels/feishu/channel_server.py` | 更新 `help_text()` |
| 6 | `channels/feishu/channel-instructions.md` | 新增 discuss mode 路由规则 |
| 7 | `.autoservice/commands/` | 创建目录结构 |
| 8 | 测试 | discover → create → list → use → delete 全流程 |

### 10.1 Dev-loop 快速注册示例

```bash
# 在飞书管理群中一次性注册 dev-loop 全套指令:
/discuss create cmd /dev-loop using-dev-loop "Dev-loop pipeline 路由"
/discuss create cmd /bootstrap project-builder "项目引导"
/discuss create cmd /test-plan test-plan-generator "生成测试计划"
/discuss create cmd /write-test test-code-writer "编写测试代码"
/discuss create cmd /run-test test-runner "执行测试"
/discuss create cmd /eval feature-eval "特性评估"
/discuss create cmd /artifacts artifact-registry "制品管理"
```

注册后在飞书中即可:

```ini
/test-plan 用户登录模块的边界测试
/run-test tests/e2e/
/eval simulate 多语言切换功能
```

## 11. 开放问题

1. __args_template 语法__: 当前仅支持 `{args}` 占位符。是否需要更复杂的模板？建议 v1 保持简单。
2. **权限控制**: create/delete/discover 是否限制为管理群？建议是——普通用户群只能使用已注册指令，不能注册。
3. **指令作用域**: 注册的指令是全局的 (所有群可用) 还是 per-chat？建议全局，简化管理。
4. **插件版本变更**: 插件更新后 skill 名可能变化，discover 重新扫描即可，但已注册指令若映射到已删除的 skill 需要提示。
5. **批量注册**: 是否支持 `/discuss create cmd --from dev-loop` 一键注册某插件下所有 skill？v1 可不做，手动逐条注册即可验证。

---

## 12. v3.1 收敛记录 (2026-04-14, dai.ming)

与 huangjiajia 当面对齐后，在原 Draft v3 基础上收敛如下，作为 v2.0 实现依据。huangjiajia 已确认后续不会再动本文档，由 dai.ming 在 PR #2 (`feat/discuss-v1.1`) 内推进实现。

### 12.1 与 v1.1 (PR #2) 的融合关系

v1.1 已落地的**常驻 worktree + session 目录**基础设施作为 v2.0 Meta Command Creator 的**共享工作台**保留，不推翻、不重写：

```
.discuss-worktree/                         ← v1.1 产物 (branch: discuss/dev)
├── .claude/skills/                        ← v2.0 用户动态创建的 skill
├── .autoservice/commands/registry.yaml    ← v2.0 命令注册表 (per-worktree)
└── .discuss/sessions/{date}-{slug}/       ← v1.1 讨论过程 + 报告
```

这个 worktree 是"命令族的 playground"：讨论过程、新建命令、注册表、生成的 skill 全部 commit 到 `discuss/dev` 分支，通过 `scripts/refine.sh --pr` cherry-pick 回流到 `dev`。不好的留在 `discuss/dev`，主分支保持干净。

### 12.2 命名约定修订

| 类别 | 语法 | 举例 | 备注 |
|---|---|---|---|
| 元指令族本身 | `/discuss` | `/discuss` (默认显示 help) | 与 v1.1 一致 |
| 元指令子命令 | `/discuss <verb> ...` | `/discuss create cmd /review evaluate "..."`<br>`/discuss list cmd`<br>`/discuss discover` | 沿用 Draft v3 空格分隔语法 |
| v1.1 深度讨论入口 | `/discuss session <verb>` | `/discuss session start "话题"`<br>`/discuss session end`<br>`/discuss session status` | 从 v1.1 的顶级 `/discuss start/end/status` 迁移到 `session` 子命令空间，避免和元指令动词冲突 |
| 动态注册的命令 | `/<name>` (**顶级**) | `/review`、`/qa`、`/test-plan` | 不加 `/discuss:` 前缀，用户体验更短 |

**关键澄清：**
- "冒号命名空间" (`/discuss:xxx`) **不采用**。元指令子命令用空格分隔（和 Draft v3 一致），动态命令直接顶级
- `/discuss session` 是 v1.1 功能保留的命名空间，内置固定，不走 registry。因为 `session` 逻辑（init_discuss 脚本 + 讨论全生命周期）比"调用一个 skill"复杂得多，不是单纯的命令→skill 映射

### 12.3 registry.yaml 位置修订

**原 Draft v3 §4.1**: `.autoservice/commands/registry.yaml`
**v3.1 修订为**: `.discuss-worktree/.autoservice/commands/registry.yaml`

原因：动态注册产生的 skill 文件也写在 worktree 内，注册表和 skill 实体要在同一 git 作用域，否则无法通过 `discuss/dev` 分支一起版本化和 PR 回流。

`channel_server.py` 读取路径：
```python
registry_path = (PROJECT_ROOT / ".discuss-worktree" /
                 ".autoservice" / "commands" / "registry.yaml")
```

若 worktree 尚未创建，registry 为空；首次 `/discuss create cmd` 时由 v1.1 的 `init_discuss.py` 延伸逻辑顺带初始化。

### 12.4 权限模型

沿用 v1.1 已有的 `admin_chat_ids` 白名单（commit `b34ec4f` — ADMIN_CHAT_ID 逗号分隔多群）：

- `/discuss` 及其所有子命令仅在管理群 (admin_chat_ids) 生效
- 动态注册后的顶级命令（`/review` 等）在**所有群**都可用（已注册指令的使用不受管理群限制，但注册/删除必须在管理群）
- 普通群发 `/discuss xxx` 走普通消息路由，不触发指令逻辑（与现状一致）

### 12.5 Hot-reload 策略

两层分别处理：

| 层 | 机制 | 重启需要？ |
|---|---|---|
| Claude Code skill (`.claude/skills/*/SKILL.md`) | Claude Code 每个 turn 扫描目录发现 skill | ❌ 不需要，下一 turn 生效 |
| channel_server 的 registry.yaml | 每次匹配未知 `/<cmd>` 时 lazy reload YAML（文件修改时间戳变了就重读） | ❌ 不需要，修改文件即生效 |

→ **用户在 worktree 内自建 skill 并注册后，下一条消息即可使用，整个链路无需重启任何进程。**

### 12.6 与已合并 PR 的协作边界

| 相关 PR | 影响 | v2.0 如何共存 |
|---|---|---|
| PR #4 CC Pool | 提供预热 Claude 实例池 | v2.0 不直接集成，pool_mode 开时实例共用 instructions，registry 路由仍在 channel_server 层 |
| PR #7 三层架构 | `feishu/` → `channels/feishu/` | v2.0 实现放 `channels/feishu/channel_server.py`（L1），registry.yaml 放 worktree 内（L2/L3 作用域） |
| PR #11 CC Pool Phase 2 | `channel_server.py` 增 `_handle_pool_message` | v2.0 的 `/discuss` 拦截层在 `_handle_admin_message` 内，不与 pool 路径冲突 |

### 12.7 v2.0 MVP 范围（5 项）

1. `channels/feishu/channel_server.py` 内 `_handle_admin_message` 新增 `/discuss create cmd`、`/discuss list cmd`、`/discuss delete cmd`、`/discuss discover` 四个元指令入口
2. `channel_server` 启动时加载 registry.yaml，运行时 `on_message`（管理群 + 普通群）拦截所有 `/<registered_cmd>` 并按 registry 查找 skill，构造带 `runtime_mode=discuss` + `discuss_meta={skill, args}` 的消息注入队列
3. `channels/feishu/channel-instructions.md` 新增 `discuss` mode 路由段：按 `discuss_meta.skill` 动态分发
4. 把现有 v1.1 的 `/discuss "topic"` / `/discuss end` / `/discuss status` 顶级命令迁移到 `/discuss session <verb>` 命名空间下（改现有 `_handle_discuss_command` 的 parser）
5. `scripts/refine.sh` 的 `--pr` 路径补充文档：说明如何从 `discuss/dev` 分支 cherry-pick 新建 skill 回主线

**v2.1 延后**：per-user-worktree 隔离（需要 CC Pool sticky-by-chat_id + per-instance cwd 支持，依赖项不齐）、thread 监管窗（R-CMD-3）、卡片化报告输出。

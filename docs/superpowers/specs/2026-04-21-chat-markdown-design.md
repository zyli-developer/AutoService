# Chat Markdown Rendering — Design

**Date**: 2026-04-21 · **Author**: brainstorm session (hjj.gemini@gmail.com + Claude) · **Status**: DRAFT (pending user review)

## 1. Goal

Add markdown rendering to all four chat surfaces in the frontend workspace, but only for **assistant/agent output** (not user-typed input). Enables structured replies — lists, code blocks with syntax highlighting, tables, links — that agents already produce and humans want to read.

## 2. Scope — 4 chat surfaces

| Surface | File | Role it exercises |
|---------|------|-------------------|
| customer-chat | `frontend/apps/customer-chat/src/components/MessageBubble.tsx` | EndUser ↔ customer agent |
| operator-console copilot | `frontend/apps/operator-console/src/components/CopilotView.tsx` | Operator ↔ copilot agent (suggestions) |
| operator-console conversation | `frontend/apps/operator-console/src/components/ConversationFeed.tsx` | Operator observing EndUser ↔ agent flow |
| admin-portal ManagementChat | `frontend/apps/admin-portal/src/components/ManagementChat.tsx` | Admin (A) ↔ `_master` platform agent |
| admin-portal ChatTab | `frontend/apps/admin-portal/src/components/tenant/ChatTab.tsx` | Tenant admin ↔ `_local_admin` fork-side agent |

Five integration points across four apps. Rendered only when `role === "assistant"` (or the app's equivalent role discriminator — see §5).

## 3. Out of scope (M3+ backlog)

- Dark-mode theme for code blocks (ship light theme only)
- Code-block copy-to-clipboard button
- Mermaid diagram rendering
- User-side markdown (user input renders as plain text)
- Editor-side live preview

## 4. Component — `MarkdownMessage`

### 4.1 Location

`frontend/packages/shared/MarkdownMessage.tsx` — four apps import from the shared package (single-source-of-truth monorepo convention).

### 4.2 API

```tsx
interface MarkdownMessageProps {
  content: string;                  // raw markdown text
  variant?: "chat" | "compact";     // chat = message-bubble sized; compact = sidebar/copilot
  className?: string;               // additional classes to merge
}

export function MarkdownMessage(props: MarkdownMessageProps): JSX.Element
```

### 4.3 Rendering pipeline

```
content (string)
  → ReactMarkdown
      remarkPlugins:   [remarkGfm]          ← tables, strikethrough, task lists, autolinks
      rehypePlugins:   [rehypeHighlight]    ← code block syntax highlighting via highlight.js
      components override:
        a  → <a target="_blank" rel="noopener noreferrer">
        img → null   (anti-`<img onerror>` LLM injection)
  → DOM
```

### 4.4 Security

Three layers of defense:

1. **react-markdown default** — raw HTML (`<script>`, `<iframe>`, inline event handlers) is **not parsed**; it appears as literal text. No `rehype-raw` will be installed.
2. **Call-site discipline** — four surfaces wrap `MarkdownMessage` behind a `role === "assistant"` gate. User-typed content never enters the markdown parser.
3. **Component overrides** — `<a>` forced to `target="_blank" rel="noopener noreferrer"` (anti-tabnabbing); `<img>` returns `null` (blocks `<img src=x onerror=...>` remnants from pathological LLM output).

URL schemes: react-markdown's default `urlTransform` filters out `javascript:` and `data:*` (except images); we do NOT override this. A test pins the behavior (see §7).

## 5. Integration points

### 5.1 customer-chat — MessageBubble.tsx

```tsx
// Before
<div className="bubble-body">{message.content}</div>

// After
<div className="bubble-body">
  {message.role === "assistant"
    ? <MarkdownMessage content={message.content} variant="chat" />
    : <span>{message.content}</span>
  }
</div>
```

Role discriminator: currently `message.role` string. Verify during implementation — values likely `"assistant" | "user" | "system"`.

### 5.2 operator-console — CopilotView + ConversationFeed

CopilotView uses `variant="compact"` (sidebar width is tighter).
ConversationFeed uses `variant="chat"`.

Role discriminator likely `message.sender` with values `"agent" | "user" | "operator"`. Assistant-side: treat `sender === "agent"` as the markdown path.

### 5.3 admin-portal — ManagementChat

Existing component renders agent replies as plain text. Swap in `MarkdownMessage` for `role === "assistant"` (or equivalent) path.

### 5.4 admin-portal — ChatTab (batch-11)

State shape `{role: "user" | "assistant", content: string}` already exists. One-line swap.

## 6. Styling — `MarkdownMessage.css`

- Import `highlight.js/styles/github.css` (light theme) at component top.
- `.md-msg ul, .md-msg ol { margin: 4px 0; padding-left: 20px; }` — compact so lists don't balloon bubble height.
- `.md-msg pre { max-width: 100%; overflow-x: auto; font-size: 12px; line-height: 1.4; }` — code blocks scroll horizontally rather than wrap or overflow the bubble.
- `.md-msg code:not(pre code) { background: rgba(0,0,0,0.05); padding: 0 4px; border-radius: 3px; font-family: var(--font-mono); }` — inline code differentiates from body text.
- `.md-msg table { border-collapse: collapse; margin: 4px 0; } .md-msg th, .md-msg td { border: 1px solid var(--cs-border, #e5e5e5); padding: 4px 8px; }`
- `.md-msg blockquote { border-left: 3px solid var(--cs-accent, #0066cc); padding-left: 8px; margin: 4px 0; color: var(--cs-text-secondary, #666); }`
- `.md-chat` sets `font-size: 13px; line-height: 1.5;` (message bubble body)
- `.md-compact` sets `font-size: 12px; line-height: 1.4;` (copilot sidebar)

Reuses existing `cs-*` CSS variables where they exist; falls back to literal hex so the component works in apps that don't have the CSS token set yet.

## 7. Tests

### 7.1 Shared component — `frontend/packages/shared/MarkdownMessage.test.tsx` (~8 tests)

| Test | Asserts |
|------|---------|
| basic CommonMark | `**bold**` → `<strong>`; `*italic*` → `<em>`; inline `` `code` `` → `<code>` |
| lists | `- a\n- b` → `<ul>` with 2 `<li>` |
| blockquote | `> quoted` → `<blockquote>` |
| GFM table | pipe-separated table → `<table><thead>...<tbody>` |
| GFM task list | `- [ ] todo\n- [x] done` → 2 checkboxes (second `checked`) |
| code block + highlight | `` ```python\nprint()\n``` `` → `<pre class="...hljs-language-python...">` |
| link hardening | `[go](https://example.com)` → `<a href target="_blank" rel="noopener noreferrer">` |
| image stripped | `![x](y.png)` → no `<img>` element |
| raw HTML escaped | `<script>alert(1)</script>` → text node, no `<script>` element |
| `javascript:` href | `[x](javascript:alert(1))` → link href does NOT contain `javascript:` (default urlTransform filters) |

### 7.2 Per-surface regression tests

Each of the four chat surfaces gets one additional test:

- assistant message with `**bold**` → `<strong>` present
- user message with `**bold**` → literal text `**bold**` (no `<strong>`)

## 8. Dependencies

Add to `frontend/packages/shared/package.json`:

```json
{
  "dependencies": {
    "react-markdown": "^9.0.1",
    "remark-gfm": "^4.0.0",
    "rehype-highlight": "^7.0.0",
    "highlight.js": "^11.9.0"
  }
}
```

Whether the apps need to explicitly list these in their own `package.json` depends on the workspace's bundler behaviour:
- If pnpm workspace resolves transitively without hoisting quirks → shared's `dependencies` is enough.
- If Vite+pnpm refuses to bundle transitive deps (common in strict mode) → duplicate the four entries under each consuming app's `dependencies`.

The implementation plan must verify this once — `cd frontend/apps/customer-chat && npx vitest run src/__tests__/MessageBubble.test.tsx` after the shared component lands reveals it instantly (import error vs. success).

Bundle impact estimate:
- react-markdown: ~30kb gzipped
- remark-gfm: ~15kb gzipped
- rehype-highlight: ~5kb gzipped
- highlight.js: ~20kb gzipped (with common languages only)
- **Total: ~70kb gzipped added per app bundle**

Acceptable for the value delivered.

## 9. Work slices (plan outline — writing-plans will refine)

1. **shared-component**: install deps + write `MarkdownMessage.tsx` + `MarkdownMessage.css` + 10 unit tests. Land in a standalone commit; tests green before any integration.
2. **customer-chat + operator-console**: 3 integration points (MessageBubble, CopilotView, ConversationFeed) + 3 regression tests updated.
3. **admin-portal**: 2 integration points (ManagementChat, ChatTab) + 2 regression tests updated.
4. **close**: full vitest regression; eval-doc + test-diff + e2e-report + register + link per `docs/plans/m2/cc-prompt-templates.md` §6.

Each batch produces its own artifact trio; overall feature gets a combined run report.

## 10. Risks + mitigations

| Risk | Mitigation |
|------|-----------|
| LLM outputs raw HTML that looks like code but is partially interpreted | react-markdown default + `rehypeHighlight` (not `rehype-raw`); pinned by test 7.1 `raw HTML escaped` |
| Bundle bloat | ~70kb gzipped is acceptable; lazy-loaded highlight.js theme if complaints arise in M3 |
| Per-surface role-discriminator drift (different apps name it differently) | Implementation plan enumerates each surface's exact field name before touching code; regression tests pin the "user = plain text" invariant |
| Existing pre-wrap whitespace behaviour lost | CSS preserves `white-space: pre-wrap` inside `<pre>`; inline text flows normally (same as before) |

## 11. Non-goals

Explicitly excluded from this feature; do not add scope:
- Dark-mode theme swap
- Copy-to-clipboard buttons on code blocks
- Mermaid / KaTeX / LaTeX rendering
- User input markdown rendering
- Live preview editor
- Per-tenant markdown settings (opt-in/out)

## 12. Success criteria

- All 4 surfaces render assistant markdown identically (same component, same CSS)
- User input on all 4 surfaces renders as plain text (no formatting)
- 10 shared-component tests green
- 4 per-surface regression tests green (1 per surface; assistant formatted + user plain)
- No pre-existing chat surface tests regress
- Bundle size delta within ±10% of the estimated ~70kb

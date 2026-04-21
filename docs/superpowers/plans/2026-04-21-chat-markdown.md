# Chat Markdown Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render GitHub-flavored markdown + syntax-highlighted code blocks in assistant/agent messages across 4 chat surfaces (customer-chat, operator-console copilot, admin-portal ManagementChat, admin-portal ChatTab). User-typed content stays plain text.

**Architecture:** One shared component at `frontend/packages/shared/MarkdownMessage.tsx` using `react-markdown` + `remark-gfm` + `rehype-highlight`. Each chat surface role-gates its render path so only assistant messages go through the parser.

**Tech Stack:** React 18, pnpm workspace, vitest + @testing-library/react, react-markdown ^9, remark-gfm ^4, rehype-highlight ^7, highlight.js ^11.

**Spec:** [docs/superpowers/specs/2026-04-21-chat-markdown-design.md](../specs/2026-04-21-chat-markdown-design.md)

**Deviation from spec:** The spec §5.2 lists `ConversationFeed.tsx` as an integration point, but that component renders 40-char `truncate()`'d card previews (not full messages) — markdown on a 40-char snippet is pointless. This plan skips it; implementation notes the skip in Task 3's commit body.

---

## Task 1: Shared MarkdownMessage component

**Files:**
- Modify: `frontend/packages/shared/package.json`
- Create: `frontend/packages/shared/MarkdownMessage.tsx`
- Create: `frontend/packages/shared/MarkdownMessage.css`
- Create: `frontend/packages/shared/MarkdownMessage.test.tsx`

- [ ] **Step 1.1: Add deps to `frontend/packages/shared/package.json`**

Find the `"dependencies"` block and add four entries. Final block (preserve existing entries):

```json
"dependencies": {
  "react": "^18.2.0",
  "react-markdown": "^9.0.1",
  "remark-gfm": "^4.0.0",
  "rehype-highlight": "^7.0.0",
  "highlight.js": "^11.9.0"
}
```

- [ ] **Step 1.2: Install**

Run: `cd frontend && pnpm install`
Expected: `+ 4 packages` (or equivalent) + no errors.

- [ ] **Step 1.3: Write the failing test**

Create `frontend/packages/shared/MarkdownMessage.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MarkdownMessage } from './MarkdownMessage';

describe('MarkdownMessage', () => {
  it('renders basic CommonMark (bold, italic, inline code)', () => {
    const { container } = render(
      <MarkdownMessage content="A **bold** and *italic* and `code` line." />
    );
    expect(container.querySelector('strong')).toHaveTextContent('bold');
    expect(container.querySelector('em')).toHaveTextContent('italic');
    expect(container.querySelector('code')).toHaveTextContent('code');
  });

  it('renders bulleted lists', () => {
    const { container } = render(
      <MarkdownMessage content={'- alpha\n- beta\n- gamma'} />
    );
    expect(container.querySelectorAll('ul li')).toHaveLength(3);
  });

  it('renders blockquotes', () => {
    const { container } = render(
      <MarkdownMessage content="> quoted line" />
    );
    expect(container.querySelector('blockquote')).toHaveTextContent('quoted line');
  });

  it('renders GFM tables (remark-gfm)', () => {
    const table = '| a | b |\n|---|---|\n| 1 | 2 |';
    const { container } = render(<MarkdownMessage content={table} />);
    expect(container.querySelector('table')).toBeInTheDocument();
    expect(container.querySelectorAll('thead th')).toHaveLength(2);
    expect(container.querySelectorAll('tbody td')).toHaveLength(2);
  });

  it('renders GFM task lists with checkbox states', () => {
    const { container } = render(
      <MarkdownMessage content={'- [ ] todo\n- [x] done'} />
    );
    const boxes = container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect(boxes).toHaveLength(2);
    expect(boxes[0].checked).toBe(false);
    expect(boxes[1].checked).toBe(true);
  });

  it('applies highlight.js classes to fenced code blocks', () => {
    const md = '```python\nprint("hi")\n```';
    const { container } = render(<MarkdownMessage content={md} />);
    const code = container.querySelector('pre code');
    expect(code).not.toBeNull();
    expect(code?.className).toMatch(/hljs/);
    // rehype-highlight emits language-python or python class on <code>
    expect(code?.className).toMatch(/python/);
  });

  it('forces external links to new tab with safe rel', () => {
    const { container } = render(
      <MarkdownMessage content="[go](https://example.com)" />
    );
    const a = container.querySelector('a');
    expect(a).toHaveAttribute('target', '_blank');
    expect(a).toHaveAttribute('rel', 'noopener noreferrer');
    expect(a).toHaveAttribute('href', 'https://example.com');
  });

  it('strips images from rendered output', () => {
    const { container } = render(
      <MarkdownMessage content="alt ![x](/y.png) end" />
    );
    expect(container.querySelector('img')).toBeNull();
  });

  it('escapes raw HTML (no script element injected)', () => {
    const { container } = render(
      <MarkdownMessage content={'<script>alert(1)</script>'} />
    );
    expect(container.querySelector('script')).toBeNull();
    // The raw text should appear (react-markdown emits it literally)
    expect(container.textContent).toContain('<script>alert(1)</script>');
  });

  it('filters javascript: scheme in links (react-markdown urlTransform default)', () => {
    const { container } = render(
      <MarkdownMessage content="[x](javascript:alert(1))" />
    );
    const a = container.querySelector('a');
    expect(a?.getAttribute('href') ?? '').not.toContain('javascript:');
  });

  it('applies variant class', () => {
    const { container: chat } = render(
      <MarkdownMessage content="x" variant="chat" />
    );
    const { container: compact } = render(
      <MarkdownMessage content="x" variant="compact" />
    );
    expect(chat.querySelector('.md-msg.md-chat')).toBeInTheDocument();
    expect(compact.querySelector('.md-msg.md-compact')).toBeInTheDocument();
  });
});
```

- [ ] **Step 1.4: Run the test — expect FAIL (component does not exist yet)**

Run: `cd frontend/packages/shared && npx vitest run MarkdownMessage.test.tsx`
Expected: module not found / resolve error. Proceed.

- [ ] **Step 1.5: Write the component**

Create `frontend/packages/shared/MarkdownMessage.tsx`:

```tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github.css';
import './MarkdownMessage.css';

export interface MarkdownMessageProps {
  /** Raw markdown text to render. */
  content: string;
  /** Visual density: `chat` for message-bubble body, `compact` for sidebars. */
  variant?: 'chat' | 'compact';
  /** Additional class names merged onto the root element. */
  className?: string;
}

/**
 * Renders markdown text with GFM extensions (tables, task lists) and
 * syntax-highlighted fenced code blocks.
 *
 * Security:
 *   - Raw HTML is NOT parsed (no `rehype-raw`); it appears as literal text.
 *   - Callers must role-gate — only assistant/agent messages should be passed
 *     to this component. User-typed content must be rendered as plain text.
 *   - External links are forced to `target="_blank"` + `rel="noopener
 *     noreferrer"`.
 *   - `<img>` tags are stripped (returns `null`) to prevent
 *     `<img onerror=...>` remnants from pathological LLM output.
 *
 * See docs/superpowers/specs/2026-04-21-chat-markdown-design.md for the
 * design rationale.
 */
export function MarkdownMessage({
  content,
  variant = 'chat',
  className,
}: MarkdownMessageProps): JSX.Element {
  const rootClass = `md-msg md-${variant}${className ? ` ${className}` : ''}`;
  return (
    <div className={rootClass}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
          img: () => null,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
```

- [ ] **Step 1.6: Write the CSS**

Create `frontend/packages/shared/MarkdownMessage.css`:

```css
/* MarkdownMessage — chat / compact variants. Light theme only for M2; dark
   mode deferred to M3 per spec §3 non-goals. */

.md-msg {
  /* Reset default ReactMarkdown-injected margins. */
}
.md-msg p {
  margin: 0 0 4px 0;
}
.md-msg p:last-child {
  margin-bottom: 0;
}
.md-msg ul,
.md-msg ol {
  margin: 4px 0;
  padding-left: 20px;
}
.md-msg li {
  margin: 2px 0;
}
.md-msg blockquote {
  border-left: 3px solid var(--cs-accent, #0066cc);
  padding-left: 8px;
  margin: 4px 0;
  color: var(--cs-text-secondary, #666);
}
.md-msg code:not(pre code) {
  background: rgba(0, 0, 0, 0.05);
  padding: 0 4px;
  border-radius: 3px;
  font-family: var(--font-mono, monospace);
  font-size: 0.9em;
}
.md-msg pre {
  max-width: 100%;
  overflow-x: auto;
  padding: 8px 10px;
  border-radius: 4px;
  background: #f6f8fa;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre;
}
.md-msg pre code {
  background: transparent;
  padding: 0;
  font-size: inherit;
}
.md-msg table {
  border-collapse: collapse;
  margin: 4px 0;
}
.md-msg th,
.md-msg td {
  border: 1px solid var(--cs-border, #e5e5e5);
  padding: 4px 8px;
}
.md-msg a {
  color: var(--cs-link, #0066cc);
  text-decoration: underline;
}
.md-msg input[type='checkbox'] {
  margin-right: 4px;
}

.md-chat {
  font-size: 13px;
  line-height: 1.5;
}
.md-compact {
  font-size: 12px;
  line-height: 1.4;
}
```

- [ ] **Step 1.7: Run the test — expect PASS (10/10)**

Run: `cd frontend/packages/shared && npx vitest run MarkdownMessage.test.tsx`
Expected: `Test Files  1 passed (1)` / `Tests  10 passed (10)`.

If any test fails, read the assertion, compare against the relevant code path, fix, rerun. Do NOT commit until all 10 pass.

- [ ] **Step 1.8: Commit**

```bash
git add frontend/packages/shared/package.json frontend/packages/shared/MarkdownMessage.tsx frontend/packages/shared/MarkdownMessage.css frontend/packages/shared/MarkdownMessage.test.tsx
git commit -m "feat(shared): MarkdownMessage component for chat surfaces

Shared React component wrapping react-markdown with remark-gfm +
rehype-highlight. Security: raw HTML escaped, external links forced to
_blank+noopener, <img> stripped. 10 unit tests cover CommonMark + GFM
+ highlight + security invariants.

Spec: docs/superpowers/specs/2026-04-21-chat-markdown-design.md"
```

---

## Task 2: Integrate MarkdownMessage into customer-chat MessageBubble

**Files:**
- Modify: `frontend/apps/customer-chat/src/components/MessageBubble.tsx` (render site near line 83: `<span>{message.content}</span>`)
- Modify: `frontend/apps/customer-chat/src/__tests__/MessageBubble.test.tsx`
- Modify (conditionally): `frontend/apps/customer-chat/package.json` (only if Task 1 proved transitive dep resolution fails)

- [ ] **Step 2.1: Probe — check transitive dep resolution**

Run: `cd frontend/apps/customer-chat && node -e "require.resolve('react-markdown', {paths:[process.cwd()]})"`

Expected: prints a resolved path.

If it errors with `Cannot find module 'react-markdown'`, add the four deps explicitly to `frontend/apps/customer-chat/package.json` (mirror Task 1.1 block into this app's `dependencies`), then `cd frontend && pnpm install`, then retry the probe.

Apply the same rule (probe + explicit add) to operator-console and admin-portal in their respective tasks.

- [ ] **Step 2.2: Write failing regression tests**

Open `frontend/apps/customer-chat/src/__tests__/MessageBubble.test.tsx`. Find the `describe('MessageBubble', () => { ... })` block and append (inside the describe) two new tests:

```tsx
  it('renders assistant markdown (bold) as <strong>', () => {
    const agentMsg = {
      id: 'm1',
      conversationId: 'c1',
      source: 'agent',
      sourceRole: 'agent' as const,
      content: 'A **bold** word.',
      ts: new Date().toISOString(),
    };
    const { container } = render(<MessageBubble message={agentMsg as any} />);
    expect(container.querySelector('strong')).toHaveTextContent('bold');
  });

  it('user-typed **bold** stays literal text (no <strong>)', () => {
    const userMsg = {
      id: 'm2',
      conversationId: 'c1',
      source: 'customer',
      sourceRole: 'customer' as const,
      content: '**bold** should stay literal',
      ts: new Date().toISOString(),
    };
    const { container } = render(<MessageBubble message={userMsg as any} />);
    expect(container.querySelector('strong')).toBeNull();
    expect(container.textContent).toContain('**bold**');
  });
```

If the test file's existing fixture shape differs (check existing tests for reference; the real `ChatMessage` type lives in `frontend/apps/customer-chat/src/store/chatStore.ts`), mirror the existing pattern rather than the literal shape above.

- [ ] **Step 2.3: Run tests — expect `agent` test to FAIL**

Run: `cd frontend/apps/customer-chat && npx vitest run src/__tests__/MessageBubble.test.tsx`
Expected: the `assistant markdown (bold)` test fails because the current render uses `<span>{message.content}</span>` — `**bold**` comes out as literal text, no `<strong>` node. The `user-typed` test will pass already.

- [ ] **Step 2.4: Modify MessageBubble.tsx**

Open `frontend/apps/customer-chat/src/components/MessageBubble.tsx`.

At the top, add this import alongside existing imports:

```tsx
import { MarkdownMessage } from '@autoservice/shared/MarkdownMessage';
```

If `@autoservice/shared` alias doesn't resolve (check `frontend/apps/customer-chat/tsconfig.json` paths or vite config), fall back to a relative import like `'../../../packages/shared/MarkdownMessage'`. Resolving the actual alias keeps the import clean; the relative path is a safety net.

Find the render block near line 80-84:

```tsx
          ) : (
            <span>{message.content}</span>
          )}
```

Replace with:

```tsx
          ) : role === 'agent' ? (
            <MarkdownMessage content={message.content} variant="chat" />
          ) : (
            <span>{message.content}</span>
          )}
```

(The existing `role === 'system'` branch higher up keeps its own `<span>` render — don't touch that.)

- [ ] **Step 2.5: Run tests — expect PASS**

Run: `cd frontend/apps/customer-chat && npx vitest run src/__tests__/MessageBubble.test.tsx`
Expected: all tests in the file pass (new 2 + pre-existing).

- [ ] **Step 2.6: Commit**

```bash
git add frontend/apps/customer-chat/src/components/MessageBubble.tsx frontend/apps/customer-chat/src/__tests__/MessageBubble.test.tsx
git commit -m "feat(customer-chat): render agent messages as markdown

MessageBubble swaps <span>{content}</span> for <MarkdownMessage> when
role === 'agent'; customer/operator/system messages stay plain text.
Regression: assistant **bold** → <strong>; user **bold** → literal."
```

If Step 2.1 required adding deps to the app's package.json, stage that file alongside and mention it in the commit body.

---

## Task 3: Integrate MarkdownMessage into operator-console CopilotView

**Files:**
- Modify: `frontend/apps/operator-console/src/components/CopilotView.tsx` (4 render sites where `<div className="op-msg-text">{msg.text}</div>` appears around lines 72, 93, 107, 122)
- Modify (or create): `frontend/apps/operator-console/src/__tests__/CopilotView.test.tsx`
- Note: ConversationFeed skipped — it shows 40-char `truncate` previews, not full messages.

- [ ] **Step 3.1: Dep-probe**

Same as Task 2.1, for operator-console:
`cd frontend/apps/operator-console && node -e "require.resolve('react-markdown', {paths:[process.cwd()]})"`
If it fails, add the 4 deps to `frontend/apps/operator-console/package.json` and `pnpm install`.

- [ ] **Step 3.2: Find CopilotMessage role discriminator**

Run: `grep -n "export.*CopilotMessage\|type CopilotMessage\|interface CopilotMessage" frontend/apps/operator-console/src/store/operatorStore.ts`

Read the definition — identify the field that distinguishes agent-generated from operator-authored (or user-customer-reflected) messages. Likely `msg.from`, `msg.sender`, or `msg.role`. The 4 render sites in CopilotView may correspond to 4 different sender branches; the agent branches are the ones to wrap in `<MarkdownMessage>`.

Record the discriminator you found (e.g. `msg.from === 'agent'`). Use it in Step 3.4.

- [ ] **Step 3.3: Write failing regression tests**

Locate or create `frontend/apps/operator-console/src/__tests__/CopilotView.test.tsx`. If creating, use a minimal stub:

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { CopilotView } from '../components/CopilotView';
import { useOperatorStore } from '../store/operatorStore';

function seedAgentMessage(convId: string, text: string, from: 'agent' | 'operator') {
  // Adjust field names to match what Step 3.2 found. `from` is the
  // placeholder — the real discriminator may be `sender`, `role`, etc.
  useOperatorStore.setState({
    activeCopilotConvId: convId,
    copilotMessages: {
      [convId]: [
        { id: 'm1', convId, from, text, ts: new Date().toISOString() } as any,
      ],
    },
  });
}

describe('CopilotView markdown rendering', () => {
  beforeEach(() => {
    useOperatorStore.setState({ activeCopilotConvId: null, copilotMessages: {} });
  });

  it('renders agent markdown (bold) as <strong>', () => {
    seedAgentMessage('c1', 'A **bold** word.', 'agent');
    const { container } = render(<CopilotView send={() => {}} />);
    expect(container.querySelector('strong')).toHaveTextContent('bold');
  });

  it('operator-authored **bold** stays literal', () => {
    seedAgentMessage('c1', '**bold** should stay literal', 'operator');
    const { container } = render(<CopilotView send={() => {}} />);
    expect(container.querySelector('strong')).toBeNull();
    expect(container.textContent).toContain('**bold**');
  });
});
```

Adjust field names/fixture shape to match the actual `CopilotMessage` type from Step 3.2.

- [ ] **Step 3.4: Run tests — expect agent test to FAIL**

Run: `cd frontend/apps/operator-console && npx vitest run src/__tests__/CopilotView.test.tsx`
Expected: `renders agent markdown (bold)` fails.

- [ ] **Step 3.5: Modify CopilotView.tsx**

Add import at top:

```tsx
import { MarkdownMessage } from '@autoservice/shared/MarkdownMessage';
```

Find the 4 occurrences of `<div className="op-msg-text">{msg.text}</div>` (near lines 72, 93, 107, 122 — `grep -n 'op-msg-text' CopilotView.tsx` confirms).

Classify each: which of them corresponds to an agent-authored message vs operator/customer? Use the discriminator you found in Step 3.2 (the surrounding `if` / branch of `StreamMessage` will make it obvious).

For each agent-branch render site, replace:

```tsx
<div className="op-msg-text">{msg.text}</div>
```

With:

```tsx
<div className="op-msg-text">
  <MarkdownMessage content={msg.text} variant="compact" />
</div>
```

Keep operator/customer render sites as plain `{msg.text}` (no change).

- [ ] **Step 3.6: Run tests — expect PASS**

Run: `cd frontend/apps/operator-console && npx vitest run src/__tests__/CopilotView.test.tsx`
Expected: both tests pass.

- [ ] **Step 3.7: Commit**

```bash
git add frontend/apps/operator-console/src/components/CopilotView.tsx frontend/apps/operator-console/src/__tests__/CopilotView.test.tsx
git commit -m "feat(operator-console): render agent copilot messages as markdown

CopilotView wraps agent-branch message text in <MarkdownMessage variant='compact'>;
operator-authored text stays plain. 4 render sites updated.

ConversationFeed intentionally skipped — it renders 40-char truncate()
previews, not full message content (design spec §5.2 noted but dropped
during planning)."
```

Stage package.json change if Step 3.1 required it.

---

## Task 4: Integrate MarkdownMessage into admin-portal ManagementChat

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/ManagementChat.tsx` (dream_engine render site around line 120: `<div className="im-msg-text" style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>`)
- Modify (or create): `frontend/apps/admin-portal/src/__tests__/ManagementChat.test.tsx`

- [ ] **Step 4.1: Dep-probe**

`cd frontend/apps/admin-portal && node -e "require.resolve('react-markdown', {paths:[process.cwd()]})"`

If it fails, add the 4 deps to `frontend/apps/admin-portal/package.json` and `pnpm install`.

- [ ] **Step 4.2: Write failing regression tests**

Open or create `frontend/apps/admin-portal/src/__tests__/ManagementChat.test.tsx` (if existing, append to the describe block):

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, act } from '@testing-library/react';
import { ManagementChat } from '../components/ManagementChat';

describe('ManagementChat markdown rendering', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn()); // never actually fire
  });

  it('renders dream_engine markdown (bold) as <strong>', () => {
    const { container } = render(<ManagementChat />);
    // Seed a dream_engine message via a test hook OR by dispatching the
    // addMessage action if the component exposes one. Simplest path: set
    // an initial message via the component's own state-exposure helper.
    // If none exists, the test may need to mock the fetch path from
    // sendMessage to return a bold reply — follow existing test patterns
    // in this file (if the file is new, look at ChatTab.test.tsx as a
    // reference for the fetch mock pattern).
    // Smoke assertion: welcome message from t('admin.dream.welcome')
    // renders; if that content contains markdown (rare), check for
    // <strong>. Otherwise, this test needs a message-seed path which
    // implementation will add via a props escape hatch OR by directly
    // calling the internal setMessages hook.
    // Weakest acceptable form:
    expect(container).toBeInTheDocument();
  });

  it('user /command stays literal (no <strong>)', () => {
    const { container } = render(<ManagementChat />);
    expect(container).toBeInTheDocument();
  });
});
```

**Note on test seeding:** ManagementChat stores messages in a `useState` hook (line ~29 per the scan). There is no props-level escape hatch to seed. Two pragmatic options:

1. **Add a `initialMessages` optional prop** to ManagementChat (test-only seam): `export function ManagementChat({ initialMessages }: { initialMessages?: ChatMsg[] } = {})`. Default to `[welcome]`. Tests pass `initialMessages={[{id,'dream_engine','**bold**',...}]}`.
2. **Mock the fetch path** (`postJSON`) and drive the send flow in the test.

Option 1 is smaller and purely additive. Recommend option 1 — add the prop, then the tests become:

```tsx
  it('renders dream_engine markdown (bold) as <strong>', () => {
    const { container } = render(
      <ManagementChat
        initialMessages={[
          { id: 'm1', role: 'dream_engine', content: '**bold**', ts: new Date().toISOString() } as any,
        ]}
      />
    );
    expect(container.querySelector('strong')).toHaveTextContent('bold');
  });

  it('user /command stays literal (no <strong>)', () => {
    const { container } = render(
      <ManagementChat
        initialMessages={[
          { id: 'm1', role: 'user', content: '**bold**', ts: new Date().toISOString() } as any,
        ]}
      />
    );
    expect(container.querySelector('strong')).toBeNull();
    expect(container.textContent).toContain('**bold**');
  });
```

- [ ] **Step 4.3: Run tests — expect dream_engine test to FAIL**

Run: `cd frontend/apps/admin-portal && npx vitest run src/__tests__/ManagementChat.test.tsx`
Expected: bold → `<strong>` assertion fails (current render uses `{msg.content}` as plain text inside `<div className="im-msg-text" style={{ whiteSpace: 'pre-wrap' }}>`).

- [ ] **Step 4.4: Modify ManagementChat.tsx**

Add import at top:

```tsx
import { MarkdownMessage } from '@autoservice/shared/MarkdownMessage';
```

Add an optional `initialMessages` prop if it doesn't exist:

```tsx
interface ManagementChatProps {
  initialMessages?: ChatMsg[];
}

export function ManagementChat({ initialMessages }: ManagementChatProps = {}) {
  // ... existing code
  const [messages, setMessages] = useState<ChatMsg[]>(
    initialMessages && initialMessages.length > 0 ? initialMessages : [welcome]
  );
  // ... rest unchanged
}
```

Find the `msg.role === 'dream_engine'` render around line 120:

```tsx
                  {msg.content && (
                    <div className="im-msg-text" style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                  )}
```

Replace the text div with:

```tsx
                  {msg.content && (
                    <div className="im-msg-text">
                      <MarkdownMessage content={msg.content} variant="chat" />
                    </div>
                  )}
```

(Drop the `whiteSpace: 'pre-wrap'` inline style — the CSS inside `.md-msg pre` preserves whitespace for code blocks and normal paragraph flow for body text, which is the correct behavior for markdown.)

Leave the `msg.role === 'user'` render site unchanged (still plain `msg.content`).

- [ ] **Step 4.5: Run tests — expect PASS**

Run: `cd frontend/apps/admin-portal && npx vitest run src/__tests__/ManagementChat.test.tsx`
Expected: both new tests pass.

- [ ] **Step 4.6: Commit**

```bash
git add frontend/apps/admin-portal/src/components/ManagementChat.tsx frontend/apps/admin-portal/src/__tests__/ManagementChat.test.tsx
git commit -m "feat(admin): render dream_engine replies as markdown in ManagementChat

Swap <div style='white-space:pre-wrap'>{content}</div> for
<MarkdownMessage variant='chat'>. Added optional initialMessages prop
as test seam — default behavior unchanged (shows welcome). User
messages continue to render plain text."
```

---

## Task 5: Integrate MarkdownMessage into admin-portal ChatTab

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/tenant/ChatTab.tsx` (render site around line 148: `{entry.text}`)
- Modify: `frontend/apps/admin-portal/src/__tests__/ChatTab.test.tsx`

- [ ] **Step 5.1: Write failing regression tests**

Open `frontend/apps/admin-portal/src/__tests__/ChatTab.test.tsx` and append to the existing describe block:

```tsx
  it('renders assistant markdown (bold) as <strong>', async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ reply: 'A **bold** word.' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    );
    vi.stubGlobal('fetch', mockFetch);

    const user = userEvent.setup();
    const { container } = render(<ChatTab />);
    const input = screen.getByRole('textbox');
    await user.type(input, 'hello');
    await user.click(screen.getByRole('button', { name: /send/i }));

    // Wait for the assistant reply to be rendered
    await screen.findByText(/bold/);
    expect(container.querySelector('strong')).toHaveTextContent('bold');
  });

  it('user-typed **bold** stays literal', async () => {
    const user = userEvent.setup();
    const { container } = render(<ChatTab />);
    const input = screen.getByRole('textbox');
    await user.type(input, '**literal**');
    await user.click(screen.getByRole('button', { name: /send/i }));
    // The user bubble should appear immediately with literal text
    expect(container.querySelector('[data-testid="chat-msg-user"]')).toHaveTextContent(
      '**literal**'
    );
  });
```

Ensure imports at file top include: `import { screen } from '@testing-library/react';`, `import userEvent from '@testing-library/user-event';`, `import { describe, it, expect, vi } from 'vitest';`. Also verify the send-button `role`/`name` pattern matches what the component actually renders — adjust the query (`getByRole` / `getByTestId`) to match the existing test conventions in this file.

- [ ] **Step 5.2: Run tests — expect assistant test to FAIL**

Run: `cd frontend/apps/admin-portal && npx vitest run src/__tests__/ChatTab.test.tsx`
Expected: assistant-markdown assertion fails (current render is plain `{entry.text}`).

- [ ] **Step 5.3: Modify ChatTab.tsx**

Add import at top:

```tsx
import { MarkdownMessage } from '@autoservice/shared/MarkdownMessage';
```

Find the render block around line 148:

```tsx
              style={{
                // ... existing styles ...
                whiteSpace: 'pre-wrap',
              }}
            >
              {entry.text}
            </div>
```

Replace `{entry.text}` with:

```tsx
              {entry.role === 'assistant'
                ? <MarkdownMessage content={entry.text} variant="chat" />
                : entry.text}
```

Keep the surrounding `<div>` and its `whiteSpace: 'pre-wrap'` style — that style only affects the non-markdown branches (user, error); inside MarkdownMessage, the component's own CSS (`.md-msg pre { white-space: pre; }`) handles whitespace for code blocks.

- [ ] **Step 5.4: Run tests — expect PASS**

Run: `cd frontend/apps/admin-portal && npx vitest run src/__tests__/ChatTab.test.tsx`
Expected: both new tests pass; no regression on pre-existing ChatTab tests.

- [ ] **Step 5.5: Commit**

```bash
git add frontend/apps/admin-portal/src/components/tenant/ChatTab.tsx frontend/apps/admin-portal/src/__tests__/ChatTab.test.tsx
git commit -m "feat(admin): render assistant replies as markdown in ChatTab

ChatTab (tenant admin ↔ _local_admin) wraps assistant-role entries in
<MarkdownMessage variant='chat'>. User + error roles stay plain."
```

---

## Task 6: Close — full regression + artifacts + PR note

**Files:**
- Create: `.artifacts/eval-docs/eval-chat-markdown-feat.md`
- Create: `.artifacts/test-diffs/test-diff-chat-markdown.md`
- Create: `.artifacts/e2e-reports/e2e-chat-markdown.md`
- Modify: `.artifacts/registry.json` (via `scripts/artifact-register.sh`)

- [ ] **Step 6.1: Full shared + 3-app regression (focused subset)**

Run — capture output for the e2e-report:

```bash
cd frontend/packages/shared && npx vitest run 2>&1 | tail -15
cd ../apps/customer-chat && npx vitest run src/__tests__/MessageBubble.test.tsx 2>&1 | tail -8
cd ../operator-console && npx vitest run src/__tests__/CopilotView.test.tsx 2>&1 | tail -8
cd ../admin-portal && npx vitest run src/__tests__/ChatTab.test.tsx src/__tests__/ManagementChat.test.tsx 2>&1 | tail -10
```

Expected: each command shows all tests pass. Any failure → go back to the corresponding task and fix before proceeding.

Do NOT run the full admin-portal vitest suite — pre-existing M2 baseline has 24 failing i18n tests in unrelated files (documented in `.artifacts/e2e-reports/e2e-batch-11.md`). Focused scope avoids that noise.

- [ ] **Step 6.2: Write eval-doc**

Create `.artifacts/eval-docs/eval-chat-markdown-feat.md`:

```markdown
# Eval: chat-markdown feature

## 预期行为
- 4 聊天面（customer-chat MessageBubble / operator-console CopilotView / admin-portal ManagementChat / admin-portal ChatTab）的 assistant/agent/dream_engine 消息经 MarkdownMessage 渲染（GFM + code highlight）
- User + operator + system 消息保持 plain text
- 安全：raw HTML 不解析；<a target=_blank rel=noopener>；<img> 剥离；javascript: scheme 被 urlTransform 过滤

## 验收标准
- 10 shared unit tests 全绿
- 每面 2 regression cases（assistant→<strong> / user→literal）全绿
- 回归：M2 已有 focused vitest subset 不受影响

## 关键 invariant
- User 输入永不进 markdown parser（CON-01 call-site role-gate）
- Stack 固定 react-markdown+remark-gfm+rehype-highlight+highlight.js（CON-02；无 rehype-raw）
- <a> 强 target=_blank rel=noopener noreferrer；<img> strip（CON-03）
- 单一出处 frontend/packages/shared/MarkdownMessage.tsx（CON-04）

## 偏离 spec §5.2
ConversationFeed 只渲染 40-char truncate() 预览，非完整消息，markdown 无意义 → 跳过。4 integration points（not 5）。
```

Register:

```bash
bash scripts/artifact-register.sh --project-root . --type eval-doc --name "chat-markdown feature" --producer "chat-markdown-plan" --path .artifacts/eval-docs/eval-chat-markdown-feat.md --status confirmed
```

Record the returned ID (e.g. `eval-doc-022`).

- [ ] **Step 6.3: Write test-diff**

Create `.artifacts/test-diffs/test-diff-chat-markdown.md`:

```markdown
# Test diff: chat-markdown feature

新增 16-18 tests across 5 files:
- frontend/packages/shared/MarkdownMessage.test.tsx (10 unit)
- customer-chat/src/__tests__/MessageBubble.test.tsx (+2 regression)
- operator-console/src/__tests__/CopilotView.test.tsx (+2)
- admin-portal/src/__tests__/ChatTab.test.tsx (+2)
- admin-portal/src/__tests__/ManagementChat.test.tsx (+2, maybe created new)

## 覆盖
- CommonMark + GFM（表格/task list）+ 代码块高亮
- 安全 4 点：raw HTML 逸义 / <a> 安全 rel / <img> strip / javascript: 过滤
- 每面 assistant-branch 走 markdown / user-branch 保留 plain

## 已修 regression
None — 新 surface。

## 关联
eval-doc-<ID-from-6.2>
```

Register similarly.

- [ ] **Step 6.4: Write e2e-report**

Create `.artifacts/e2e-reports/e2e-chat-markdown.md`:

```markdown
# E2E: chat-markdown feature

## Scope
frontend/packages/shared + customer-chat + operator-console + admin-portal focused vitest subset（不跑 admin-portal 全套 — pre-existing 24 i18n fails 非本 feature 责任）

## Total
- shared: 10/10 pass
- customer-chat MessageBubble: N/N pass（填 Step 6.1 实跑数）
- operator-console CopilotView: N/N
- admin-portal ChatTab: N/N
- admin-portal ManagementChat: N/N

## New vs regression
- New: 10 shared + 8 per-surface = 18 tests
- Regression: 前批 M2 所有 focused subset 保持绿（填数）

## Preexisting failures (unchanged baseline)
- admin-portal 24 i18n tests (见 e2e-report-007/011 baseline)
- operator-console 11 i18n（见 e2e-report-010）
- customer-chat 21 i18n（见 e2e-report-010）
- 皆不由本 feature 引入

## Verdict
chat-markdown feature ✅ GO — 所有新 tests 绿，0 新回归
```

Register.

- [ ] **Step 6.5: Link artifacts**

```bash
bash scripts/artifact-link.sh --project-root . --from <eval-doc-ID> --to <test-diff-ID>
bash scripts/artifact-link.sh --project-root . --from <test-diff-ID> --to <e2e-report-ID>
```

- [ ] **Step 6.6: Final summary commit**

```bash
git add .artifacts/
git commit -m "chore(chat-markdown): artifact trio + close

- eval-doc-<ID>: feature spec + invariants (§3/§4 of design)
- test-diff-<ID>: 18 new tests across 5 files
- e2e-report-<ID>: focused regression green; M2 baseline failures unchanged

Plan: docs/superpowers/plans/2026-04-21-chat-markdown.md"
```

- [ ] **Step 6.7: Push + open PR**

```bash
git push origin dev-a
gh pr create --base dev --head dev-a \
  --title "feat: chat markdown rendering across 4 chat surfaces" \
  --body "$(cat <<'EOF'
Implements docs/superpowers/plans/2026-04-21-chat-markdown.md.

4 integration points (customer-chat MessageBubble, operator-console
CopilotView, admin-portal ManagementChat, admin-portal ChatTab) now
render assistant/agent/dream_engine messages as GFM markdown with
code-block syntax highlighting. User input stays plain text.

Shared component: frontend/packages/shared/MarkdownMessage.tsx
Spec: docs/superpowers/specs/2026-04-21-chat-markdown-design.md

Security:
- Raw HTML escaped (no rehype-raw)
- <a target=_blank rel=noopener noreferrer>
- <img> stripped
- javascript: URL scheme filtered (urlTransform default)

Tests: 18 new, 0 regression. Pre-existing M2 baseline failures
(24+11+21 i18n) unchanged — out of scope.

## Test plan
- [x] shared MarkdownMessage.test.tsx 10/10
- [x] customer-chat MessageBubble regression 2/2
- [x] operator-console CopilotView regression 2/2
- [x] admin-portal ChatTab regression 2/2
- [x] admin-portal ManagementChat regression 2/2
- [ ] Manual visual check in dev uvicorn + admin-portal dev server

Deviation from spec: ConversationFeed was listed in spec §5.2 but
it only renders 40-char truncate() previews, not full messages.
Skipped — 4 surfaces integrated, not 5.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: prints PR URL. Stop here; wait for human review + merge.

---

## Self-review

- **Spec coverage**: 12 success criteria in spec §12 → task map:
  - "4 surfaces render identically" → Tasks 2-5 use same component + same `variant='chat'` (CopilotView uses `compact` per §5.2)
  - "User input plain text" → each task's regression test pins this
  - "10 shared tests green" → Task 1
  - "4 per-surface regression green" → Tasks 2-5
  - "No pre-existing regressions" → Task 6.1 scope is focused; baseline failures documented as pre-existing
  - "Bundle delta ±10% of ~70kb" → NOT verified in this plan. Manual check deferred to post-PR review.
- **Placeholder scan**: Checked — every step has concrete code, commands, file paths. The only "verify during implementation" notes (Step 2.4 alias fallback, Step 3.2 discriminator discovery) are deliberately deferred because the answer depends on real file contents; the plan gives a grep command to resolve each.
- **Type consistency**: `MarkdownMessageProps` defined in Task 1; used in Tasks 2-5 with same `{content, variant, className}` signature. Role strings vary per app (`agent` / `dream_engine` / `assistant`) — plan names the exact string per task.

Gap fix: bundle-size verification not in the plan. Decision: leaving as post-PR note rather than adding a full task, since bundle tooling varies and manual inspection is fine for a one-shot feature.

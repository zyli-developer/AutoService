# UI PRD Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite 3 SPAs to match PRD `docs/prd/autoservice-full-journey.html` visual design — shared design system, floating chat widget, IM-style operator workspace, wizard-driven admin portal.

**Architecture:** Extract PRD CSS into shared `design-system` package. Each SPA imports tokens + component classes. customer-chat becomes a floating widget overlay. operator-console adopts Feishu-style IM layout. admin-portal keeps Ant Design for complex form/table but uses PRD CSS for layout.

**Tech Stack:** React 18, Vite, CSS custom properties (PRD tokens), Zustand stores (keep existing), vitest.

**Spec:** `docs/superpowers/specs/2026-04-16-prd-gap-fill-design.md` Track 2

**PRD Reference:** `docs/prd/autoservice-full-journey.html` (open in browser for visual reference)

**Branch:** dev-b

---

## Chunk 1: Design System + customer-chat

### Task 1: Design system package

**Files:**
- Create: `frontend/packages/design-system/package.json`
- Create: `frontend/packages/design-system/tokens.css`
- Create: `frontend/packages/design-system/components.css`
- Create: `frontend/packages/design-system/index.css`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "@autoservice/design-system",
  "version": "0.0.1",
  "private": true,
  "main": "index.css",
  "files": ["*.css"]
}
```

- [ ] **Step 2: Extract tokens.css from PRD HTML**

Extract all CSS custom properties from the `:root` block in `autoservice-full-journey.html`:

```css
/* frontend/packages/design-system/tokens.css */
:root {
  /* Backgrounds */
  --cream: #fff;
  --oat: #e0e2e6;
  --oat-l: #f8fafc;

  /* Text */
  --silver: #9f9b93;
  --charcoal: #55534e;

  /* M-scale: Merchant / Primary (blue) */
  --m300: #dbeafe;
  --m600: #1b61c9;
  --m800: #181d26;

  /* S-scale: Customer (cyan) */
  --s500: #3bd3fd;
  --s800: #0089ad;

  /* L-scale: Warning (yellow/amber) */
  --l400: #f8cc65;
  --l500: #fbbd41;
  --l700: #d08a11;
  --l800: #9d6a09;

  /* U-scale: Platform (purple) */
  --u300: #c1b0ff;
  --u500: #8a5cf6;
  --u800: #43089f;
  --u900: #32037d;

  /* Accent: Urgent (pink) */
  --p: #fc7981;

  /* Shadow */
  --shd: rgba(0,0,0,0.1) 0px 1px 1px, rgba(0,0,0,0.04) 0px -1px 1px inset;

  /* Typography */
  --font-sans: 'Inter', 'Noto Sans SC', ui-sans-serif, system-ui, sans-serif;
  --font-mono: 'Space Mono', ui-monospace, monospace;
}
```

- [ ] **Step 3: Extract components.css from PRD HTML**

Extract the key component classes used across all three acts. Copy directly from PRD `<style>` block — these classes: `.web-msg`, `.web-modal`, `.web-fab`, `.im-card`, `.im-block`, `.im-suggest`, `.im-handoff`, `.im-driver`, `.im-sidebar-msg`, `.im-cmd`, `.im-toggle`, `.cs-card`, `.cs-wiz-step`, `.cs-row`, `.cs-pg`, `.cs-mock`, etc.

The full extraction should be ~200 lines of CSS copied verbatim from the PRD HTML style block.

- [ ] **Step 4: Create index.css barrel**

```css
/* frontend/packages/design-system/index.css */
@import './tokens.css';
@import './components.css';
```

- [ ] **Step 5: Add to pnpm workspace**

Verify `frontend/pnpm-workspace.yaml` includes `packages/design-system`.

- [ ] **Step 6: Commit**

```bash
git add frontend/packages/design-system/
git commit -m "feat: design-system package extracted from PRD HTML"
```

### Task 2: customer-chat — merchant site background

**Files:**
- Modify: `frontend/apps/customer-chat/src/App.tsx`
- Create: `frontend/apps/customer-chat/src/components/MerchantSite.tsx`
- Modify: `frontend/apps/customer-chat/src/index.css`

- [ ] **Step 1: Add design-system dependency**

In `frontend/apps/customer-chat/package.json`, add:
```json
"@autoservice/design-system": "workspace:*"
```

Replace Tailwind import in `index.css` with:
```css
@import '@autoservice/design-system';
```
Keep custom scrollbar styles.

- [ ] **Step 2: Create MerchantSite background component**

This is the simulated "独立站" that appears behind the chat widget. Copied from PRD's `webTpl()` function:

```tsx
// frontend/apps/customer-chat/src/components/MerchantSite.tsx
export function MerchantSite() {
  return (
    <div className="web-page">
      <div className="web-nav">
        <div className="web-logo">◆ 商户独立站</div>
        <div className="web-nav-links">
          <span>首页</span><span>产品</span><span>关于</span>
        </div>
      </div>
      <div className="web-hero">
        <div className="web-hero-title">欢迎光临</div>
        <div className="web-hero-sub">7×24 智能客服为您服务</div>
      </div>
      <div className="web-features">
        <div className="web-feature-card">
          <div className="web-feature-card-title">套餐 A</div>
          基础版,适合个人
        </div>
        <div className="web-feature-card">
          <div className="web-feature-card-title">套餐 B</div>
          进阶版,本月特惠
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Write tests for new layout**

```tsx
// frontend/apps/customer-chat/src/__tests__/MerchantSite.test.tsx
import { render, screen } from '@testing-library/react';
import { MerchantSite } from '../components/MerchantSite';

describe('MerchantSite', () => {
  it('renders hero section', () => {
    render(<MerchantSite />);
    expect(screen.getByText('欢迎光临')).toBeInTheDocument();
  });
  it('renders product cards', () => {
    render(<MerchantSite />);
    expect(screen.getByText('套餐 A')).toBeInTheDocument();
    expect(screen.getByText('套餐 B')).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Commit merchant site**

```bash
git add frontend/apps/customer-chat/
git commit -m "feat: merchant site background component (PRD aligned)"
```

### Task 3: customer-chat — floating widget + chat modal

**Files:**
- Create: `frontend/apps/customer-chat/src/components/ChatFAB.tsx`
- Create: `frontend/apps/customer-chat/src/components/ChatModal.tsx`
- Modify: `frontend/apps/customer-chat/src/App.tsx`
- Remove: `frontend/apps/customer-chat/src/components/ChatLayout.tsx`
- Remove: `frontend/apps/customer-chat/src/components/ChatHeader.tsx`

- [ ] **Step 1: Create ChatFAB (floating action button)**

```tsx
// frontend/apps/customer-chat/src/components/ChatFAB.tsx
interface ChatFABProps {
  onClick: () => void;
  highlight?: boolean;
}
export function ChatFAB({ onClick, highlight = false }: ChatFABProps) {
  return (
    <>
      <div className="web-fab-call">📞</div>
      <div className={`web-fab ${highlight ? 'highlight' : ''}`} onClick={onClick}>
        💬
      </div>
    </>
  );
}
```

- [ ] **Step 2: Create ChatModal (chat window overlay)**

```tsx
// frontend/apps/customer-chat/src/components/ChatModal.tsx
import type { ChatMessage } from '../store/chatStore';
import { MessageBubble } from './MessageBubble';
import { ChatInput } from './ChatInput';

interface ChatModalProps {
  messages: ChatMessage[];
  onSend: (content: string) => void;
  onClose: () => void;
  disabled?: boolean;
}
export function ChatModal({ messages, onSend, onClose, disabled }: ChatModalProps) {
  return (
    <div className="web-modal">
      <div className="web-modal-header">
        <div className="web-modal-title">智能客服 · 在线</div>
        <div className="web-modal-close" onClick={onClose}>×</div>
      </div>
      <div className="web-modal-body">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
      </div>
      <div className="web-modal-input">
        <ChatInput onSend={onSend} disabled={disabled} />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite MessageBubble to use PRD web-msg classes**

```tsx
// frontend/apps/customer-chat/src/components/MessageBubble.tsx (rewrite)
import type { ChatMessage } from '../store/chatStore';

function resolveRole(msg: ChatMessage): 'customer' | 'agent' | 'system' {
  if (msg.visibility === 'system') return 'system';
  if (msg.sourceRole === 'customer' || msg.source.includes('customer')) return 'customer';
  return 'agent';
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const role = resolveRole(message);
  return <div className={`web-msg ${role}`}>{message.content}</div>;
}
```

- [ ] **Step 4: Rewrite App.tsx — floating widget layout**

```tsx
// frontend/apps/customer-chat/src/App.tsx (rewrite)
import { useState, useRef } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useChatStore } from './store/chatStore';
import { MerchantSite } from './components/MerchantSite';
import { ChatFAB } from './components/ChatFAB';
import { ChatModal } from './components/ChatModal';

export function App() {
  const wsUrl = `ws://${window.location.hostname}:8000/ws/customer`;
  const { send } = useWebSocket(wsUrl, 'customer-chat');
  const { messages, connectionStatus } = useChatStore();
  const [isOpen, setIsOpen] = useState(false);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSend = async (content: string) => {
    const clientMsgId = crypto.randomUUID();
    useChatStore.getState().addMessage({
      id: clientMsgId, clientMsgId, source: 'customer', sourceRole: 'customer',
      content, visibility: 'public', timestamp: new Date().toISOString(),
      sequenceNumber: 0, status: 'sending',
    });
    useChatStore.getState().setAgentTyping(true);
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    typingTimerRef.current = setTimeout(() => {
      useChatStore.getState().setAgentTyping(false);
    }, 30_000);
    try {
      const convId = useChatStore.getState().conversationId;
      await send('customer_message', {
        content, client_msg_id: clientMsgId,
        ...(convId ? { conversation_id: convId } : {}),
      });
    } catch {
      useChatStore.getState().setAgentTyping(false);
    }
  };

  return (
    <div className="web-canvas">
      <MerchantSite />
      {isOpen ? (
        <ChatModal
          messages={messages}
          onSend={handleSend}
          onClose={() => setIsOpen(false)}
          disabled={connectionStatus !== 'open'}
        />
      ) : null}
      <ChatFAB onClick={() => setIsOpen(true)} highlight={!isOpen} />
    </div>
  );
}
```

- [ ] **Step 5: Remove old layout components**

Delete `ChatLayout.tsx`, `ChatHeader.tsx`, `ConnectionBanner.tsx` (functionality absorbed into ChatModal).

- [ ] **Step 6: Update tests for new structure**

Update existing tests to work with new component names. Key changes:
- `integration.test.tsx` — look for `web-modal` instead of `chat-header`
- `MessageBubble.test.tsx` — test `web-msg customer` / `web-msg agent` classes

- [ ] **Step 7: Run tests**

Run: `pnpm --filter @autoservice/customer-chat test`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/apps/customer-chat/
git commit -m "feat: customer-chat floating widget layout (PRD aligned)"
```

---

## Chunk 2: operator-console

### Task 4: operator-console — IM-style layout

**Files:**
- Create: `frontend/apps/operator-console/src/components/IMTitlebar.tsx`
- Create: `frontend/apps/operator-console/src/components/IMSidebar.tsx`
- Create: `frontend/apps/operator-console/src/components/IMMain.tsx`
- Create: `frontend/apps/operator-console/src/components/ConversationFeed.tsx`
- Create: `frontend/apps/operator-console/src/components/IMInput.tsx`
- Modify: `frontend/apps/operator-console/src/components/WorkspacePage.tsx`
- Modify: `frontend/apps/operator-console/src/index.css`

- [ ] **Step 1: Add design-system dependency + replace CSS**

In `package.json` add `"@autoservice/design-system": "workspace:*"`.
Replace `index.css` content with `@import '@autoservice/design-system';` + app-specific overrides.

- [ ] **Step 2: Create IMTitlebar**

Matches PRD `.im-titlebar`:
```tsx
export function IMTitlebar() {
  return (
    <div className="im-titlebar">
      <div className="im-titlebar-dots"><span/><span/><span/></div>
      <div className="im-workspace-name">商户客服工作区</div>
    </div>
  );
}
```

- [ ] **Step 3: Create IMSidebar**

Matches PRD `.im-sidebar` with channel list, active state, unread badges:
- Workspace header with operator name + online dot
- Section titles (频道 / 直接消息)
- Channel items with `#` prefix, `.active` class, `.im-channel-badge` for unread count
- Wire to `useOperatorStore` for active channel state

- [ ] **Step 4: Create ConversationFeed**

Matches PRD `.im-card` + `.im-block` structure:
- Avatar squares (34px, colored by role)
- Message body with author + bot tag + timestamp
- im-block cards with title + status badge + meta
- Special message types: `.im-suggest` (yellow), `.im-handoff` (pink), `.im-driver` (blue), `.im-sidebar-msg` (purple)

- [ ] **Step 5: Create CopilotView and TakeoverView**

Two display modes matching PRD:
- **Copilot**: relay lines (客户说/拟回复), yellow suggestion bar, `im-system` refresh indicator
- **Takeover**: blue driver messages, purple sidebar messages, `/release` command prompt

- [ ] **Step 6: Rewrite WorkspacePage with IM layout**

```tsx
<div className="im-w">
  <IMTitlebar />
  <div className="im-body">
    <IMSidebar />
    <div className="im-main">
      <IMMainHeader />
      <ConversationFeed />
      <IMInput />
    </div>
  </div>
</div>
```

- [ ] **Step 7: Remove Ant Design dependency**

Remove `antd` and `@ant-design/icons` from `package.json`. Update all imports.

- [ ] **Step 8: Update tests**

Rewrite tests to query new component structure (im-sidebar, im-card, etc.)

- [ ] **Step 9: Run tests**

Run: `pnpm --filter @autoservice/operator-console test`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add frontend/apps/operator-console/
git commit -m "feat: operator-console IM-style layout (PRD aligned)"
```

---

## Chunk 3: admin-portal

### Task 5: admin-portal — wizard stepper + layout

**Files:**
- Modify: `frontend/apps/admin-portal/src/components/WizardTab.tsx`
- Create: `frontend/apps/admin-portal/src/components/wizard/WizardStepper.tsx`
- Modify: all wizard step components
- Modify: `frontend/apps/admin-portal/src/index.css`

- [ ] **Step 1: Add design-system dependency**

Add `"@autoservice/design-system": "workspace:*"` to package.json.
Import in index.css alongside Ant Design styles (keep Ant for Table/Form).

- [ ] **Step 2: Create WizardStepper matching PRD `.cs-wiz-step`**

Horizontal pill stepper: 5 steps, done/current/pending states, arrow separators.

```tsx
const STEPS = ['上传', '权限', '预演', '合规', '可用'];
// cs-wiz-step.done = m300 bg, m800 text
// cs-wiz-step.cur = m800 bg, white text
// cs-wiz-step default = oat-l bg, silver text
```

- [ ] **Step 3: Rewrite wizard steps to use PRD `.cs-card` layout**

Each step uses `.cs-card` with `.cs-ct` title, `.cs-row` key-value rows, `.cs-pg` progress indicator.
Keep Ant Design `Upload` and `Form.Item` for actual form inputs, wrapped in PRD card shells.

- [ ] **Step 4: Rewrite DashboardTab to platform monitor style**

Match PRD `pB()` function: SLA metric cards + monospace event stream.

- [ ] **Step 5: Rewrite NotificationsTab to IM conversation style**

Match PRD `imC()` function: Dream Engine dialog cards, proposal blocks with risk badges, `/approve` `/edit` `/reject` command input, canary progress bar.

- [ ] **Step 6: Update tests**

Update test queries for new class names and structure.

- [ ] **Step 7: Run tests**

Run: `pnpm --filter @autoservice/admin-portal test`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/apps/admin-portal/
git commit -m "feat: admin-portal PRD-aligned wizard + dashboard + notifications"
```

### Task 6: Final integration + cross-SPA test

- [ ] **Step 1: Run all frontend tests**

```bash
pnpm --filter @autoservice/customer-chat test
pnpm --filter @autoservice/operator-console test
pnpm --filter @autoservice/admin-portal test
```
Expected: ALL PASS

- [ ] **Step 2: Start all 3 dev servers and visual check**

```bash
pnpm --filter @autoservice/customer-chat dev    # :5173
pnpm --filter @autoservice/operator-console dev  # :5174
pnpm --filter @autoservice/admin-portal dev      # :5175
```

Visual checklist against PRD HTML:
- [ ] customer-chat: floating widget on merchant site background
- [ ] operator-console: IM sidebar + conversation cards + copilot/takeover modes
- [ ] admin-portal: pill stepper wizard + monitor dashboard + IM notifications

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: UI PRD full alignment complete (3 SPAs + design system)"
```

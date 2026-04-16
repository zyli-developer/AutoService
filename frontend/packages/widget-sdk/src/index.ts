/**
 * @autoservice/widget-sdk
 *
 * Embeddable chat widget that connects to an AutoService web channel.
 * Works in two modes:
 *   1. Vanilla JS — call `AutoServiceWidget.init({ serverUrl })` to mount the widget.
 *   2. React — import `ChatWidget` component.
 */

// ── Types ──────────────────────────────────────────────────────────────

export interface WidgetConfig {
  /** WebSocket endpoint of the AutoService web channel, e.g. "wss://example.com/ws" */
  serverUrl: string;
  /** DOM element or CSS selector to mount the widget into. Defaults to document.body. */
  container?: HTMLElement | string;
  /** Initial greeting message shown before user sends anything. */
  greeting?: string;
  /** Position of the floating button. Default: "bottom-right". */
  position?: "bottom-right" | "bottom-left";
  /** Primary theme color (CSS value). Default: "#4F46E5". */
  themeColor?: string;
  /** Title shown in the chat header. */
  title?: string;
  /** Token for authenticated sessions. */
  token?: string;
}

export interface WidgetInstance {
  /** Open the chat panel. */
  open(): void;
  /** Close the chat panel. */
  close(): void;
  /** Toggle the chat panel. */
  toggle(): void;
  /** Remove the widget from the DOM and disconnect. */
  destroy(): void;
}

// ── Helpers ────────────────────────────────────────────────────────────

function resolveContainer(
  containerOrSelector?: HTMLElement | string,
): HTMLElement {
  if (!containerOrSelector) return document.body;
  if (typeof containerOrSelector === "string") {
    const el = document.querySelector<HTMLElement>(containerOrSelector);
    if (!el)
      throw new Error(
        `@autoservice/widget-sdk: container "${containerOrSelector}" not found`,
      );
    return el;
  }
  return containerOrSelector;
}

// ── Core ───────────────────────────────────────────────────────────────

/**
 * Initialise the AutoService chat widget.
 *
 * ```ts
 * import { init } from "@autoservice/widget-sdk";
 * const widget = init({ serverUrl: "wss://my-app.example.com/ws" });
 * ```
 */
export function init(config: WidgetConfig): WidgetInstance {
  const container = resolveContainer(config.container);
  const position = config.position ?? "bottom-right";
  const themeColor = config.themeColor ?? "#4F46E5";
  const title = config.title ?? "Chat";

  // ── Host element ────────────────────────────────────────────────────
  const host = document.createElement("div");
  host.id = "autoservice-widget-root";
  host.setAttribute(
    "style",
    `position:fixed;${position === "bottom-right" ? "right:24px" : "left:24px"};bottom:24px;z-index:2147483647;font-family:system-ui,sans-serif;`,
  );
  container.appendChild(host);

  // ── Floating button ─────────────────────────────────────────────────
  const btn = document.createElement("button");
  btn.setAttribute(
    "style",
    `width:56px;height:56px;border-radius:50%;background:${themeColor};color:#fff;border:none;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.15);display:flex;align-items:center;justify-content:center;font-size:24px;`,
  );
  btn.textContent = "\u{1F4AC}";
  btn.setAttribute("aria-label", "Open chat");
  host.appendChild(btn);

  // ── Chat panel (hidden by default) ──────────────────────────────────
  const panel = document.createElement("div");
  panel.setAttribute(
    "style",
    "display:none;position:absolute;bottom:72px;right:0;width:380px;height:520px;background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.12);overflow:hidden;flex-direction:column;",
  );

  const header = document.createElement("div");
  header.setAttribute(
    "style",
    `padding:14px 16px;background:${themeColor};color:#fff;font-weight:600;font-size:15px;`,
  );
  header.textContent = title;
  panel.appendChild(header);

  const messages = document.createElement("div");
  messages.setAttribute(
    "style",
    "flex:1;overflow-y:auto;padding:12px 16px;",
  );
  if (config.greeting) {
    const greeting = document.createElement("div");
    greeting.setAttribute(
      "style",
      "background:#f3f4f6;padding:8px 12px;border-radius:8px;font-size:14px;margin-bottom:8px;",
    );
    greeting.textContent = config.greeting;
    messages.appendChild(greeting);
  }
  panel.appendChild(messages);

  const inputArea = document.createElement("div");
  inputArea.setAttribute(
    "style",
    "padding:10px 12px;border-top:1px solid #e5e7eb;display:flex;gap:8px;",
  );
  const input = document.createElement("input");
  input.setAttribute(
    "style",
    "flex:1;border:1px solid #d1d5db;border-radius:8px;padding:8px 12px;font-size:14px;outline:none;",
  );
  input.placeholder = "Type a message...";
  inputArea.appendChild(input);
  panel.appendChild(inputArea);

  host.appendChild(panel);

  // ── State ───────────────────────────────────────────────────────────
  let isOpen = false;

  function setOpen(open: boolean) {
    isOpen = open;
    panel.style.display = open ? "flex" : "none";
    btn.textContent = open ? "\u2715" : "\u{1F4AC}";
    if (open) input.focus();
  }

  btn.addEventListener("click", () => setOpen(!isOpen));

  // ── WebSocket (lazy connect) ────────────────────────────────────────
  let ws: WebSocket | null = null;

  function ensureConnection() {
    if (ws && ws.readyState <= WebSocket.OPEN) return;
    const url = new URL(config.serverUrl);
    if (config.token) url.searchParams.set("token", config.token);
    ws = new WebSocket(url.toString());
    ws.addEventListener("message", (ev) => {
      const bubble = document.createElement("div");
      bubble.setAttribute(
        "style",
        "background:#f3f4f6;padding:8px 12px;border-radius:8px;font-size:14px;margin-bottom:8px;",
      );
      bubble.textContent = String(ev.data);
      messages.appendChild(bubble);
      messages.scrollTop = messages.scrollHeight;
    });
  }

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && input.value.trim()) {
      ensureConnection();
      const text = input.value.trim();
      const bubble = document.createElement("div");
      bubble.setAttribute(
        "style",
        `background:${themeColor};color:#fff;padding:8px 12px;border-radius:8px;font-size:14px;margin-bottom:8px;align-self:flex-end;text-align:right;`,
      );
      bubble.textContent = text;
      messages.appendChild(bubble);
      messages.scrollTop = messages.scrollHeight;
      ws?.send(JSON.stringify({ type: "message", content: text }));
      input.value = "";
    }
  });

  // ── Public API ──────────────────────────────────────────────────────
  return {
    open: () => setOpen(true),
    close: () => setOpen(false),
    toggle: () => setOpen(!isOpen),
    destroy: () => {
      ws?.close();
      host.remove();
    },
  };
}

// ── Convenience: global AutoServiceWidget for <script> usage ──────────
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).AutoServiceWidget = { init };
}

export default { init };

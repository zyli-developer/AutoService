interface ChatFABProps {
  onClick: () => void;
  highlight?: boolean;
}

export function ChatFAB({ onClick, highlight = false }: ChatFABProps) {
  return (
    <>
      <div className="web-fab-call">📞</div>
      <div
        className={`web-fab ${highlight ? 'highlight' : ''}`}
        onClick={onClick}
        role="button"
        aria-label="Open chat"
      >
        💬
      </div>
    </>
  );
}

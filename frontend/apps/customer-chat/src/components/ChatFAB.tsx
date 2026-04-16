interface ChatFABProps {
  onClick: () => void;
  highlight?: boolean;
}

export function ChatFAB({ onClick, highlight = false }: ChatFABProps) {
  return (
    <>
      <div className="web-fab-call" data-testid="fab-call">{'\uD83D\uDCDE'}</div>
      <div
        className={`web-fab ${highlight ? 'highlight' : ''}`}
        onClick={onClick}
        data-testid="chat-fab"
        role="button"
        aria-label="Open chat"
      >
        {'\uD83D\uDCAC'}
      </div>
    </>
  );
}

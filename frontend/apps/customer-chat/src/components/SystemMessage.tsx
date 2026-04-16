interface SystemMessageProps {
  content: string;
}

export function SystemMessage({ content }: SystemMessageProps) {
  return (
    <div className="web-msg system" data-testid="system-message">
      {content}
    </div>
  );
}

interface SystemMessageProps {
  content: string;
}

export function SystemMessage({ content }: SystemMessageProps) {
  return (
    <div
      data-testid="system-message"
      className="flex justify-center my-2 px-4"
    >
      <span className="text-xs text-slate-400 bg-slate-100 rounded-full px-3 py-1">
        {content}
      </span>
    </div>
  );
}

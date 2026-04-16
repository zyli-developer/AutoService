interface TypingIndicatorProps {
  visible: boolean;
}

export function TypingIndicator({ visible }: TypingIndicatorProps) {
  if (!visible) return null;
  return (
    <div data-testid="typing-indicator" className="flex px-4 py-1 justify-start">
      <div className="bg-slate-100 rounded-2xl rounded-bl-sm px-4 py-3 flex gap-1 items-center">
        <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:0ms]" />
        <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:150ms]" />
        <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:300ms]" />
      </div>
    </div>
  );
}

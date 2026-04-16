import React from 'react';

interface ChatLayoutProps {
  header: React.ReactNode;
  messageList: React.ReactNode;
  input: React.ReactNode;
}

export function ChatLayout({ header, messageList, input }: ChatLayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-white">
      <div className="flex-shrink-0">{header}</div>
      <div className="flex-1 overflow-hidden flex flex-col">{messageList}</div>
      <div className="flex-shrink-0">{input}</div>
    </div>
  );
}

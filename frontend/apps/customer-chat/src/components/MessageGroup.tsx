import type { ChatMessage } from '../store/chatStore';
import { SenderAvatar } from './SenderAvatar';
import { MessageBubble } from './MessageBubble';

export interface MessageGroupData {
  source: string;
  sourceRole: ChatMessage['sourceRole'];
  senderName?: string;
  avatarUrl?: string;
  messages: ChatMessage[];
}

const GROUP_TIME_GAP_MS = 5 * 60 * 1000; // 5 minutes

export function groupMessages(messages: ChatMessage[]): MessageGroupData[] {
  const groups: MessageGroupData[] = [];

  for (const msg of messages) {
    const lastGroup = groups[groups.length - 1];
    const lastMsg = lastGroup?.messages[lastGroup.messages.length - 1];

    const sameSource = lastGroup?.source === msg.source;
    const withinTimeGap =
      lastMsg &&
      new Date(msg.timestamp).getTime() - new Date(lastMsg.timestamp).getTime() <
        GROUP_TIME_GAP_MS;

    if (sameSource && withinTimeGap) {
      lastGroup.messages.push(msg);
    } else {
      groups.push({
        source: msg.source,
        sourceRole: msg.sourceRole,
        senderName: msg.senderName,
        avatarUrl: msg.avatarUrl,
        messages: [msg],
      });
    }
  }

  return groups;
}

interface MessageGroupProps {
  group: MessageGroupData;
}

export function MessageGroup({ group }: MessageGroupProps) {
  const isCustomer = group.sourceRole === 'customer';

  return (
    <div className={`flex flex-col ${isCustomer ? 'items-end' : 'items-start'} mb-1`}>
      {!isCustomer && group.senderName && (
        <span className="ml-10 mb-0.5 text-xs text-slate-500 px-4">{group.senderName}</span>
      )}
      <div className={`flex ${isCustomer ? 'flex-row-reverse' : 'flex-row'} items-end gap-1`}>
        {!isCustomer && (
          <div className="self-end mb-1">
            <SenderAvatar name={group.senderName} avatarUrl={group.avatarUrl} />
          </div>
        )}
        <div className="flex flex-col gap-0.5">
          {group.messages.map((msg, i) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              showTimestamp={i === group.messages.length - 1}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

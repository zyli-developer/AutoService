import { describe, it, expect, beforeEach } from 'vitest';
import { useOperatorStore, initialState, type CopilotMessage } from '../store/operatorStore';

beforeEach(() => {
  useOperatorStore.setState(initialState);
});

describe('operatorStore copilot actions', () => {
  it('TC-06: openCopilot sets activeCopilotConvId', () => {
    useOperatorStore.getState().openCopilot('conv-123');
    expect(useOperatorStore.getState().activeCopilotConvId).toBe('conv-123');
  });

  it('TC-07: closeCopilot clears activeCopilotConvId', () => {
    useOperatorStore.getState().openCopilot('conv-123');
    useOperatorStore.getState().closeCopilot();
    expect(useOperatorStore.getState().activeCopilotConvId).toBeNull();
  });

  it('TC-08: addCopilotMessage appends to array', () => {
    const msg1: CopilotMessage = { id: 'm1', text: 'hello', sender: 'operator', ts: '2026-04-16T10:00:00Z' };
    const msg2: CopilotMessage = { id: 'm2', text: 'reply', sender: 'agent', ts: '2026-04-16T10:01:00Z' };

    useOperatorStore.getState().addCopilotMessage('conv-1', msg1);
    useOperatorStore.getState().addCopilotMessage('conv-1', msg2);

    const messages = useOperatorStore.getState().copilotMessages['conv-1'];
    expect(messages).toHaveLength(2);
    expect(messages[0]).toEqual(msg1);
    expect(messages[1]).toEqual(msg2);
  });
});

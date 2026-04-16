import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useOperatorStore } from '../store/operatorStore';
import { UnreadBadge } from '../components/UnreadBadge';

describe('UnreadBadge', () => {
  it('TC-01: badge hidden when unreadCounts is 0', () => {
    render(
      <UnreadBadge squadId="sq-A">
        <span>Squad A</span>
      </UnreadBadge>,
    );
    const wrapper = screen.getByTestId('unread-badge-sq-A');
    // Ant Design Badge with count=0 does not render .ant-badge-count or renders it hidden
    const countEl = wrapper.querySelector('.ant-badge-count');
    expect(countEl === null || countEl.classList.contains('ant-badge-count-hidden') ||
      getComputedStyle(countEl).display === 'none').toBe(true);
  });

  it('TC-02: badge shows count when > 0', () => {
    useOperatorStore.getState().incrementUnread('sq-A');
    useOperatorStore.getState().incrementUnread('sq-A');
    useOperatorStore.getState().incrementUnread('sq-A');
    render(
      <UnreadBadge squadId="sq-A">
        <span>Squad A</span>
      </UnreadBadge>,
    );
    const wrapper = screen.getByTestId('unread-badge-sq-A');
    expect(wrapper).toHaveTextContent('3');
  });

  it('TC-03: clearUnread resets count', () => {
    useOperatorStore.getState().incrementUnread('sq-B');
    useOperatorStore.getState().incrementUnread('sq-B');
    useOperatorStore.getState().clearUnread('sq-B');
    expect(useOperatorStore.getState().unreadCounts['sq-B']).toBe(0);
  });
});

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginPage } from '../components/LoginPage';
import { useOperatorStore, initialState } from '../store/operatorStore';

beforeEach(() => {
  useOperatorStore.setState(initialState);
});

describe('LoginPage', () => {
  it('TC-006: renders login form with operatorId input, token input, and submit button', () => {
    render(<LoginPage />);
    expect(screen.getByTestId('input-operator-id')).toBeInTheDocument();
    expect(screen.getByTestId('input-token')).toBeInTheDocument();
    expect(screen.getByTestId('btn-login')).toBeInTheDocument();
  });

  it('TC-007: filling form and clicking login sets isLoggedIn=true', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.type(screen.getByTestId('input-token'), 'tok-xyz');
    await user.click(screen.getByTestId('btn-login'));
    expect(useOperatorStore.getState().isLoggedIn).toBe(true);
    expect(useOperatorStore.getState().operatorId).toBe('op-001');
  });

  it('TC-008: empty operatorId -- login button is disabled', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    const btn = screen.getByTestId('btn-login');
    expect(btn).toBeDisabled();
    await user.click(btn);
    expect(useOperatorStore.getState().isLoggedIn).toBe(false);
  });

  it('TC-009: empty token is accepted (token is optional)', async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByTestId('input-operator-id'), 'op-001');
    await user.click(screen.getByTestId('btn-login'));
    expect(useOperatorStore.getState().isLoggedIn).toBe(true);
  });
});

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ErrorBoundary from '../../components/ErrorBoundary';

function Bomb(): never {
  throw new Error('boom from child');
}

describe('ErrorBoundary', () => {
  it('renders children normally when nothing throws', () => {
    render(
      <ErrorBoundary>
        <p>All good</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText('All good')).toBeInTheDocument();
  });

  it('catches a throwing child, shows the fallback with the error text, and never renders nothing', () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { container } = render(
      <ErrorBoundary title="Custom title">
        <Bomb />
      </ErrorBoundary>,
    );
    expect(container).not.toBeEmptyDOMElement();
    expect(screen.getByText('Custom title')).toBeInTheDocument();
    expect(screen.getByText('boom from child')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start over' })).toBeInTheDocument();
    consoleErrorSpy.mockRestore();
  });

  it('calls onReset and clears its own error state when "Start over" is clicked', async () => {
    const onReset = vi.fn();
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const user = userEvent.setup();

    let shouldThrow = true;
    function MaybeBomb() {
      if (shouldThrow) throw new Error('first render throws');
      return <p>Recovered</p>;
    }

    render(
      <ErrorBoundary onReset={onReset}>
        <MaybeBomb />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('button', { name: 'Start over' })).toBeInTheDocument();

    shouldThrow = false;
    await user.click(screen.getByRole('button', { name: 'Start over' }));
    expect(onReset).toHaveBeenCalledOnce();
    expect(screen.getByText('Recovered')).toBeInTheDocument();
    consoleErrorSpy.mockRestore();
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../analytics/ga', () => ({ trackEvent: vi.fn() }));

import ProcessingScreen from '../../components/ProcessingScreen';
import type { JobDoc } from '../../hooks/useJobSnapshot';

const baseJobDoc: JobDoc = {
  status: 'processing', stage: 3, output_data: null, error_data: null, name: '',
};

describe('ProcessingScreen', () => {
  it('renders steps 1-2 done, step 3 active, steps 4-5 waiting for stage=3', () => {
    render(<ProcessingScreen jobDoc={baseJobDoc} snapshotError={null} jobExists={true} onRestart={vi.fn()} />);
    const nodes = document.querySelectorAll('.step-node');
    expect(nodes[0].className).toContain('done');
    expect(nodes[1].className).toContain('done');
    expect(nodes[2].className).toContain('active');
    expect(nodes[3].className).toContain('waiting');
    expect(nodes[4].className).toContain('waiting');
    expect(screen.getByText('Simplifying language')).toBeInTheDocument();
  });

  it('renders the normal step list (not a terminal state) while exists is still null (not yet loaded)', () => {
    render(<ProcessingScreen jobDoc={null} snapshotError={null} jobExists={null} onRestart={vi.fn()} />);
    expect(document.querySelector('.step-list')).not.toBeNull();
    expect(screen.queryByText(/session ended/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/lost connection/i)).not.toBeInTheDocument();
  });

  it('renders the reconnect message and a "Start over" button when snapshotError is set', async () => {
    const onRestart = vi.fn();
    const user = userEvent.setup();
    render(<ProcessingScreen jobDoc={baseJobDoc} snapshotError={new Error('boom')} jobExists={null} onRestart={onRestart} />);
    expect(screen.getByText(/lost connection/i)).toBeInTheDocument();
    expect(document.querySelector('.step-list')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Start over' }));
    expect(onRestart).toHaveBeenCalledOnce();
  });

  it('renders a "session ended" terminal message and a "Start over" button when the job doc is confirmed missing', async () => {
    const onRestart = vi.fn();
    const user = userEvent.setup();
    render(<ProcessingScreen jobDoc={null} snapshotError={null} jobExists={false} onRestart={onRestart} />);
    expect(screen.getByText(/session ended/i)).toBeInTheDocument();
    expect(screen.getByText(/nothing was saved/i)).toBeInTheDocument();
    expect(document.querySelector('.step-list')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Start over' }));
    expect(onRestart).toHaveBeenCalledOnce();
  });

  it('prioritizes the "session ended" state over a stale snapshotError when the doc is confirmed missing', () => {
    render(<ProcessingScreen jobDoc={null} snapshotError={new Error('boom')} jobExists={false} onRestart={vi.fn()} />);
    expect(screen.getByText(/session ended/i)).toBeInTheDocument();
    expect(screen.queryByText(/lost connection/i)).not.toBeInTheDocument();
  });

  it('moves focus to the screen heading on mount', () => {
    render(<ProcessingScreen jobDoc={baseJobDoc} snapshotError={null} jobExists={true} onRestart={vi.fn()} />);
    expect(document.activeElement?.tagName).toBe('H1');
    expect(document.activeElement).toHaveTextContent(/creating your simplified care plan/i);
  });

  it('exposes an aria-live polite region announcing the current active step', () => {
    render(<ProcessingScreen jobDoc={baseJobDoc} snapshotError={null} jobExists={true} onRestart={vi.fn()} />);
    const live = document.querySelector('[aria-live="polite"]');
    expect(live).not.toBeNull();
    expect(live).toHaveTextContent('Step 3 of 5: Simplifying language');
  });

  it('updates the live region as the active step advances', () => {
    const { rerender } = render(
      <ProcessingScreen jobDoc={baseJobDoc} snapshotError={null} jobExists={true} onRestart={vi.fn()} />,
    );
    rerender(
      <ProcessingScreen jobDoc={{ ...baseJobDoc, stage: 4 }} snapshotError={null} jobExists={true} onRestart={vi.fn()} />,
    );
    expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent('Step 4 of 5');
  });
});

describe('ProcessingScreen watchdog', () => {
  const WATCHDOG_MS = 6 * 60 * 1000;

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('does not show a "taking longer than expected" notice before the watchdog elapses', () => {
    render(<ProcessingScreen jobDoc={baseJobDoc} snapshotError={null} jobExists={true} onRestart={vi.fn()} />);
    act(() => { vi.advanceTimersByTime(WATCHDOG_MS - 1); });
    expect(screen.queryByText(/taking longer than expected/i)).not.toBeInTheDocument();
  });

  it('shows the watchdog notice and a "Start over" button once the timeout elapses, alongside the still-visible step list', () => {
    const onRestart = vi.fn();
    render(<ProcessingScreen jobDoc={baseJobDoc} snapshotError={null} jobExists={true} onRestart={onRestart} />);
    act(() => { vi.advanceTimersByTime(WATCHDOG_MS); });

    expect(screen.getByText(/taking longer than expected/i)).toBeInTheDocument();
    // The job could technically still complete, so the step list stays visible.
    expect(document.querySelector('.step-list')).not.toBeNull();
    expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent(/taking longer than usual/i);

    screen.getByRole('button', { name: 'Start over' }).click();
    expect(onRestart).toHaveBeenCalledOnce();
  });

  it('does not show the watchdog notice once the doc is confirmed gone, even after the timeout elapses', () => {
    render(<ProcessingScreen jobDoc={null} snapshotError={null} jobExists={false} onRestart={vi.fn()} />);
    act(() => { vi.advanceTimersByTime(WATCHDOG_MS); });
    expect(screen.queryByText(/taking longer than expected/i)).not.toBeInTheDocument();
    expect(screen.getByText(/session ended/i)).toBeInTheDocument();
  });

  it('clears the watchdog timer on unmount, so no state update fires after the screen is gone', () => {
    const { unmount } = render(
      <ProcessingScreen jobDoc={baseJobDoc} snapshotError={null} jobExists={true} onRestart={vi.fn()} />,
    );
    unmount();
    expect(() => act(() => { vi.advanceTimersByTime(WATCHDOG_MS); })).not.toThrow();
  });
});

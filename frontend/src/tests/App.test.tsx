import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../analytics/ga', () => ({ trackEvent: vi.fn() }));

// HomePage pulls in a lot (Firebase, the whole upload/processing/result
// machine); for this test we only care that whatever HomePage renders is
// wrapped in App's error boundary, so replace it with a component that
// throws on demand.
let homePageShouldThrow = false;
vi.mock('../pages/HomePage', () => ({
  default: () => {
    if (homePageShouldThrow) throw new Error('HomePage exploded');
    return <div>Home page content</div>;
  },
}));

import App from '../App';

describe('App', () => {
  it('renders the route content normally when nothing throws', () => {
    homePageShouldThrow = false;
    render(<MemoryRouter><App /></MemoryRouter>);
    expect(screen.getByText('Home page content')).toBeInTheDocument();
  });

  it('catches an uncaught exception from a page and shows a recoverable error, never a blank page', () => {
    homePageShouldThrow = true;
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { container } = render(<MemoryRouter><App /></MemoryRouter>);
    expect(container).not.toBeEmptyDOMElement();
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start over' })).toBeInTheDocument();
    consoleErrorSpy.mockRestore();
    homePageShouldThrow = false;
  });
});

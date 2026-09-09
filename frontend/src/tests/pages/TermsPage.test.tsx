import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TermsPage from '../../pages/TermsPage';

describe('TermsPage', () => {
  it('renders without throwing and contains a Back-to-Simplify link to /', () => {
    // This page can open in its own tab (footer's target="_blank" link), so the label
    // names the destination rather than implying it returns to work in progress elsewhere.
    render(<MemoryRouter><TermsPage /></MemoryRouter>);
    const link = screen.getByRole('link', { name: /back to simplify/i });
    expect(link).toHaveAttribute('href', '/');
  });

  it('renders the approved Terms & Conditions copy, including the rate limit', () => {
    render(<MemoryRouter><TermsPage /></MemoryRouter>);
    expect(
      screen.getByRole('heading', { name: /terms & conditions for simplify/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/currently 5 per hour, subject to change without notice/i)).toBeInTheDocument();
  });
});

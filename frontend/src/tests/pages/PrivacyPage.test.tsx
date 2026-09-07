import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PrivacyPage from '../../pages/PrivacyPage';

describe('PrivacyPage', () => {
  it('renders without throwing and contains a Back-to-Simplify link to /', () => {
    // This page can open in its own tab (footer's target="_blank" link), so the label
    // names the destination rather than implying it returns to work in progress elsewhere.
    render(<MemoryRouter><PrivacyPage /></MemoryRouter>);
    const link = screen.getByRole('link', { name: /back to simplify/i });
    expect(link).toHaveAttribute('href', '/');
  });

  it('renders the approved Privacy Policy copy', () => {
    render(<MemoryRouter><PrivacyPage /></MemoryRouter>);
    expect(
      screen.getByRole('heading', { name: /privacy policy — simplify/i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/do not upload real, identifiable patient health information \(phi\)/i)
    ).toBeInTheDocument();
  });
});

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
      screen.getByRole('heading', { name: /privacy policy for simplify/i })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a substitute for professional medical advice/i)
    ).toBeInTheDocument();
  });

  it('renders the contact email as a mailto link', () => {
    render(<MemoryRouter><PrivacyPage /></MemoryRouter>);
    const link = screen.getByRole('link', { name: /tejitpabari99@gmail\.com/i });
    expect(link).toHaveAttribute('href', 'mailto:tejitpabari99@gmail.com');
  });
});

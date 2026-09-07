import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

const trackEventMock = vi.fn();
vi.mock('../../analytics/ga', () => ({ trackEvent: (...a: unknown[]) => trackEventMock(...a) }));

import Footer from '../../components/Footer';

describe('Footer', () => {
  it('opens both legal links in a new tab with noopener/noreferrer, and keeps their real routes as href', () => {
    render(<MemoryRouter><Footer /></MemoryRouter>);

    const privacyLink = screen.getByRole('link', { name: 'Privacy Policy' });
    expect(privacyLink).toHaveAttribute('href', '/privacy');
    expect(privacyLink).toHaveAttribute('target', '_blank');
    expect(privacyLink).toHaveAttribute('rel', 'noopener noreferrer');

    const termsLink = screen.getByRole('link', { name: 'Terms & Conditions' });
    expect(termsLink).toHaveAttribute('href', '/terms');
    expect(termsLink).toHaveAttribute('target', '_blank');
    expect(termsLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('still fires the legal_link_clicked analytics event on click', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><Footer /></MemoryRouter>);

    await user.click(screen.getByRole('link', { name: 'Privacy Policy' }));
    expect(trackEventMock).toHaveBeenCalledWith({
      name: 'legal_link_clicked',
      params: { link: 'privacy', source_screen: '/' },
    });

    await user.click(screen.getByRole('link', { name: 'Terms & Conditions' }));
    expect(trackEventMock).toHaveBeenCalledWith({
      name: 'legal_link_clicked',
      params: { link: 'terms', source_screen: '/' },
    });
  });
});

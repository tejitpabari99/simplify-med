import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from 'react';
import { createPortal } from 'react-dom';

interface MedicalTermProps {
  term: string;
  definition: string;
  imgUrl?: string | null;
  altText?: string | null;
}

export default function MedicalTerm({ term, definition, imgUrl, altText }: MedicalTermProps) {
  const [open, setOpen] = useState(false);
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({});
  const popoverId = useId();
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open || !ref.current) return;

    const updatePosition = () => {
      const rect = ref.current?.getBoundingClientRect();
      if (!rect) return;

      const gap = 8;
      const width = Math.min(300, window.innerWidth - 24);
      const left = Math.min(
        Math.max(rect.left, 12),
        Math.max(12, window.innerWidth - width - 12),
      );
      const showAbove = rect.top > 140;
      const verticalPosition = showAbove
        ? { bottom: window.innerHeight - rect.top + gap }
        : { top: rect.bottom + gap };

      setPopoverStyle({
        position: 'fixed',
        left,
        width,
        zIndex: 1000,
        ...verticalPosition,
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);

    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleFocusIn = (event: FocusEvent) => {
      if (!ref.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('focusin', handleFocusIn);

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('focusin', handleFocusIn);
    };
  }, [open]);

  const handleKeyDown = (event: KeyboardEvent<HTMLSpanElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setOpen(current => !current);
      return;
    }

    if (event.key === 'Escape') {
      event.stopPropagation();
      setOpen(false);
    }
  };

  return (
    <span
      ref={ref}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      style={{ position: 'relative', display: 'inline' }}
    >
      <span
        className="medical-term"
        onClick={() => setOpen(current => !current)}
        onKeyDown={handleKeyDown}
        tabIndex={0}
        role="button"
        aria-expanded={open}
        aria-describedby={open ? popoverId : undefined}
        aria-label={`${term}: ${definition}`}
      >
        {term}
      </span>
      {open && createPortal(
        <span
          id={popoverId}
          className="medical-term-popover"
          role="tooltip"
          style={popoverStyle}
        >
          {imgUrl && (
            <img
              src={imgUrl}
              alt={altText ?? term}
              className="medical-term-popover-image"
            />
          )}
          <span className="medical-term-popover-definition">{definition}</span>
        </span>,
        document.body,
      )}
    </span>
  );
}

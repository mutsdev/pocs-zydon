import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  label?: string;
  error?: string;
  options: SelectOption[];
  placeholder?: string;
  value?: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
  className?: string;
  id?: string;
}

export default function Select({
  label,
  error,
  options,
  placeholder = 'Selecione...',
  value,
  onChange,
  disabled = false,
  className = '',
  id,
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const selectId = id || label?.toLowerCase().replace(/\s+/g, '-');

  const selected = options.find((o) => o.value === value);

  // Close on click outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [open]);

  // Scroll focused item into view
  useEffect(() => {
    if (open && focusedIndex >= 0 && listRef.current) {
      const item = listRef.current.children[focusedIndex] as HTMLElement;
      item?.scrollIntoView({ block: 'nearest' });
    }
  }, [focusedIndex, open]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;

    switch (e.key) {
      case 'Enter':
      case ' ':
        e.preventDefault();
        if (!open) {
          setOpen(true);
          setFocusedIndex(options.findIndex((o) => o.value === value));
        } else if (focusedIndex >= 0) {
          onChange?.(options[focusedIndex].value);
          setOpen(false);
        }
        break;
      case 'Escape':
        setOpen(false);
        break;
      case 'ArrowDown':
        e.preventDefault();
        if (!open) {
          setOpen(true);
          setFocusedIndex(0);
        } else {
          setFocusedIndex((prev) => Math.min(prev + 1, options.length - 1));
        }
        break;
      case 'ArrowUp':
        e.preventDefault();
        if (open) {
          setFocusedIndex((prev) => Math.max(prev - 1, 0));
        }
        break;
    }
  }

  return (
    <div className={`flex flex-col gap-1.5 ${className}`} ref={containerRef}>
      {label && (
        <label htmlFor={selectId} className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
          {label}
        </label>
      )}
      <div className="relative">
        <button
          type="button"
          id={selectId}
          role="combobox"
          aria-expanded={open}
          aria-haspopup="listbox"
          disabled={disabled}
          onClick={() => !disabled && setOpen(!open)}
          onKeyDown={handleKeyDown}
          className={`
            w-full px-3 py-2 text-sm rounded-md border text-left
            focus:outline-none focus:ring-2 focus:border-transparent
            disabled:opacity-50 disabled:cursor-not-allowed
            transition-all duration-200 flex items-center justify-between gap-2
          `}
          style={{
            backgroundColor: 'var(--color-surface)',
            borderColor: error ? 'var(--color-danger)' : 'var(--color-border)',
            color: selected ? 'var(--color-text)' : 'var(--color-text-secondary)',
            ...({ '--tw-ring-color': error ? 'var(--color-danger)' : 'var(--color-primary-light)' } as React.CSSProperties),
          }}
        >
          <span className="truncate">{selected ? selected.label : placeholder}</span>
          <ChevronDown
            size={16}
            className={`shrink-0 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
            style={{ color: 'var(--color-text-secondary)' }}
          />
        </button>

        {open && (
          <ul
            ref={listRef}
            role="listbox"
            className="absolute z-50 w-full mt-1 py-1 rounded-md border max-h-60 overflow-auto"
            style={{
              boxShadow: 'var(--shadow-overlay)',
              backgroundColor: 'var(--color-surface)',
              borderColor: 'var(--color-border)',
            }}
          >
            {options.map((opt, idx) => (
              <li
                key={opt.value}
                role="option"
                aria-selected={opt.value === value}
                className={`
                  px-3 py-2 text-sm cursor-pointer flex items-center justify-between gap-2
                  transition-colors duration-100
                `}
                style={{
                  backgroundColor: focusedIndex === idx ? 'var(--color-primary-bg)' : undefined,
                  color: opt.value === value ? 'var(--color-primary-text)' : 'var(--color-text)',
                }}
                onMouseEnter={() => setFocusedIndex(idx)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChange?.(opt.value);
                  setOpen(false);
                }}
              >
                <span className="truncate">{opt.label}</span>
                {opt.value === value && <Check size={16} style={{ color: 'var(--color-primary-text)' }} />}
              </li>
            ))}
          </ul>
        )}
      </div>
      {error && <p className="text-meta" style={{ color: 'var(--color-danger)' }}>{error}</p>}
    </div>
  );
}

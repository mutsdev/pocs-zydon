import { forwardRef } from 'react';
import type { InputHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className = '', id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');
    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={inputId} className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={`
            w-full px-3 py-2 text-sm rounded-md border
            focus:outline-none focus:ring-2 focus:border-transparent
            disabled:opacity-60 disabled:cursor-not-allowed
            transition-all duration-200
            ${className}
          `}
          style={{
            backgroundColor: 'var(--color-surface)',
            borderColor: error ? 'var(--color-danger)' : 'var(--color-border)',
            color: 'var(--color-text)',
            ...({ '--tw-ring-color': error ? 'var(--color-danger)' : 'var(--color-primary-light)' } as React.CSSProperties),
          }}
          {...props}
        />
        {error && <p className="text-meta" style={{ color: 'var(--color-danger)' }}>{error}</p>}
      </div>
    );
  }
);

Input.displayName = 'Input';
export default Input;

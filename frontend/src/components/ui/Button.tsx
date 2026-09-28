import { forwardRef } from 'react';
import type { ButtonHTMLAttributes } from 'react';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const sizeClasses: Record<Size, string> = {
  sm: 'px-3 py-1.5 text-sm',
  md: 'px-4 py-2 text-sm',
  lg: 'px-5 py-2.5 text-base',
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', className = '', disabled, children, style, ...props }, ref) => {
    const base = 'inline-flex items-center justify-center gap-2 font-medium rounded-md cursor-pointer transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';

    const variants: Record<Variant, { className: string; style?: React.CSSProperties }> = {
      primary: {
        className: '',
        style: {
          backgroundColor: 'var(--color-primary)',
          color: 'var(--color-on-primary)',
          '--tw-ring-color': 'var(--color-primary-light)',
        } as React.CSSProperties,
      },
      secondary: {
        className: 'border',
        style: {
          backgroundColor: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
          color: 'var(--color-text)',
        },
      },
      danger: {
        className: 'text-white hover:opacity-90',
        style: { backgroundColor: 'var(--color-danger)', '--tw-ring-color': 'var(--color-danger)' } as React.CSSProperties,
      },
      ghost: {
        className: 'hover:bg-[var(--color-nav-hover)]',
        style: { color: 'var(--color-text-secondary)', '--tw-ring-color': 'var(--color-border)' } as React.CSSProperties,
      },
    };

    const v = variants[variant];

    return (
      <button
        ref={ref}
        disabled={disabled}
        className={`${base} ${v.className} ${sizeClasses[size]} ${className}`}
        style={{ ...v.style, ...style }}
        onMouseEnter={(e) => {
          if (variant === 'primary') {
            (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--color-primary-hover)';
          }
          props.onMouseEnter?.(e);
        }}
        onMouseLeave={(e) => {
          if (variant === 'primary') {
            (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--color-primary)';
          }
          props.onMouseLeave?.(e);
        }}
        {...props}
      >
        {children}
      </button>
    );
  }
);

Button.displayName = 'Button';
export default Button;

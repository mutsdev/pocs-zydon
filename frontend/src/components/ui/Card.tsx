import type { HTMLAttributes, ReactNode } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ className = '', children, style, ...props }: CardProps) {
  return (
    <div
      className={`rounded-lg ${className}`}
      style={{ backgroundColor: 'var(--color-surface)', boxShadow: 'var(--shadow-card)', ...style }}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className = '', children, ...props }: CardProps) {
  return (
    <div className={`flex flex-col gap-1 p-5 pb-2 ${className}`} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({ className = '', children, style, ...props }: CardProps) {
  return (
    <h3 className={`text-base font-semibold leading-none ${className}`} style={{ color: 'var(--color-text)', ...style }} {...props}>
      {children}
    </h3>
  );
}

export function CardDescription({ className = '', children, style, ...props }: CardProps) {
  return (
    <p className={`text-sm ${className}`} style={{ color: 'var(--color-text-secondary)', ...style }} {...props}>
      {children}
    </p>
  );
}

export function CardContent({ className = '', children, ...props }: CardProps) {
  return (
    <div className={`px-5 pb-5 flex-1 flex flex-col ${className}`} {...props}>
      {children}
    </div>
  );
}

export default Card;

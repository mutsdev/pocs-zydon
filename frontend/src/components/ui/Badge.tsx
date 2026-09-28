interface BadgeProps {
  variant: 'success' | 'danger' | 'info' | 'warning' | 'neutral';
  children: React.ReactNode;
  dot?: boolean;
}

const tom = (n: string) => ({ backgroundColor: `var(--color-${n}-bg)`, color: `var(--color-${n})`, borderColor: `var(--color-${n}-border)` });
const variantStyles: Record<BadgeProps['variant'], React.CSSProperties> = {
  success: tom('success'),
  danger: tom('danger'),
  info: tom('info'),
  warning: tom('warning'),
  neutral: { backgroundColor: 'var(--color-nav-hover)', color: 'var(--color-text-secondary)', borderColor: 'var(--color-border)' },
};

export default function Badge({ variant, children, dot = false }: BadgeProps) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-0.5 text-meta font-medium rounded-full border"
      style={variantStyles[variant]}
    >
      {dot && <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: 'currentColor' }} />}
      {children}
    </span>
  );
}

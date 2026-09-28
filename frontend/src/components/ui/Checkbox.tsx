import { Check } from 'lucide-react';

interface CheckboxProps {
  label?: string;
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
  id?: string;
}

export default function Checkbox({
  label,
  checked = false,
  onChange,
  disabled = false,
  className = '',
  id,
}: CheckboxProps) {
  const checkboxId = id || label?.toLowerCase().replace(/\s+/g, '-');

  return (
    <label
      htmlFor={checkboxId}
      className={`inline-flex items-center gap-2.5 cursor-pointer select-none ${disabled ? 'opacity-50 cursor-not-allowed' : ''} ${className}`}
    >
      <button
        type="button"
        role="checkbox"
        id={checkboxId}
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onChange?.(!checked)}
        className={`
          w-[18px] h-[18px] rounded shrink-0
          border flex items-center justify-center
          transition-all duration-200
          focus:outline-none focus:ring-2 focus:ring-offset-1
        `}
        style={{
          backgroundColor: checked ? 'var(--color-primary)' : 'var(--color-surface)',
          borderColor: checked ? 'var(--color-primary)' : 'var(--color-border)',
          '--tw-ring-color': 'var(--color-primary-light)',
          '--tw-ring-offset-color': 'var(--color-surface)',
        } as React.CSSProperties}
      >
        {checked && <Check size={13} strokeWidth={3} style={{ color: 'var(--color-on-primary)' }} />}
      </button>
      {label && (
        <span className="text-sm" style={{ color: 'var(--color-text)' }}>
          {label}
        </span>
      )}
    </label>
  );
}

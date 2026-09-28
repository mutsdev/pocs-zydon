interface RadioOption {
  value: string;
  label: string;
}

interface RadioGroupProps {
  label?: string;
  options: RadioOption[];
  value?: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
  direction?: 'vertical' | 'horizontal';
  className?: string;
  name?: string;
}

export default function RadioGroup({
  label,
  options,
  value,
  onChange,
  disabled = false,
  direction = 'vertical',
  className = '',
  name: _name,
}: RadioGroupProps) {
  return (
    <fieldset className={`flex flex-col gap-1.5 ${className}`}>
      {label && (
        <legend className="text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
          {label}
        </legend>
      )}
      <div className={`flex ${direction === 'vertical' ? 'flex-col' : 'flex-row flex-wrap'} gap-2.5`} role="radiogroup">
        {options.map((opt) => {
          const isSelected = opt.value === value;
          return (
            <label
              key={opt.value}
              className={`inline-flex items-center gap-2.5 cursor-pointer select-none ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <button
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={disabled}
                onClick={() => !disabled && onChange?.(opt.value)}
                className={`
                  w-[18px] h-[18px] rounded-full shrink-0
                  border-2 flex items-center justify-center
                  transition-all duration-200
                  focus:outline-none focus:ring-2 focus:ring-offset-1
                `}
                style={{
                  borderColor: isSelected ? 'var(--color-primary)' : 'var(--color-border)',
                  '--tw-ring-color': 'var(--color-primary-light)',
                  '--tw-ring-offset-color': 'var(--color-surface)',
                } as React.CSSProperties}
              >
                {isSelected && (
                  <div
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: 'var(--color-primary)' }}
                  />
                )}
              </button>
              <span className="text-sm" style={{ color: 'var(--color-text)' }}>
                {opt.label}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

import type { ReactNode } from 'react'
import { AlertCircle } from 'lucide-react'

export function Pagina({ titulo, subtitulo, acao, children }: { titulo: string; subtitulo?: string; acao?: ReactNode; children: ReactNode }) {
  return (
    <div className="p-4 md:p-6 flex flex-col gap-6 max-w-7xl mx-auto">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>{titulo}</h1>
          {subtitulo && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{subtitulo}</p>}
        </div>
        {acao && <div className="ml-auto flex flex-wrap gap-2">{acao}</div>}
      </div>
      {children}
    </div>
  )
}

export function Aviso({ tipo = 'warning', titulo, children }: { tipo?: 'warning' | 'danger' | 'info' | 'success'; titulo: string; children?: ReactNode }) {
  return (
    <div className="flex gap-3 rounded-lg p-4" style={{ backgroundColor: `var(--color-${tipo}-bg)`, color: `var(--color-${tipo})` }}>
      <AlertCircle size={18} className="shrink-0 mt-0.5" />
      <div className="flex flex-col gap-1">
        <div className="text-sm font-semibold">{titulo}</div>
        {children && <div className="text-sm" style={{ color: 'var(--color-text)' }}>{children}</div>}
      </div>
    </div>
  )
}

export function Vazio({ titulo, texto, acao }: { titulo: string; texto: string; acao?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center gap-2 py-6 px-4">
      <div className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>{titulo}</div>
      <p className="text-sm max-w-md" style={{ color: 'var(--color-text-secondary)' }}>{texto}</p>
      {acao && <div className="mt-3">{acao}</div>}
    </div>
  )
}

export function Esqueleto({ linhas = 4 }: { linhas?: number }) {
  return (
    <div className="flex flex-col gap-3 p-5">
      {Array.from({ length: linhas }).map((_, i) => (
        <div key={i} className="h-5 rounded animate-pulse" style={{ backgroundColor: 'var(--color-border)', width: `${90 - i * 12}%` }} />
      ))}
    </div>
  )
}

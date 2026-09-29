import { useRef } from 'react'
import { FileSpreadsheet, FileText, Paperclip, X } from 'lucide-react'
import { ACEITOS } from '../../lib/anexo'

interface Props { arquivo: File | null; onChange: (arquivo: File | null) => void; rotulo?: string; ajuda?: string; desativado?: boolean }

function tamanho(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
}

export default function CampoAnexo({ arquivo, onChange, rotulo = 'Catálogo do cliente (opcional)', ajuda, desativado }: Props) {
  const entrada = useRef<HTMLInputElement>(null)
  const Icone = arquivo && /\.(xlsx|xls|csv)$/i.test(arquivo.name) ? FileSpreadsheet : FileText
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>{rotulo}</span>
      <input ref={entrada} type="file" accept={ACEITOS} className="hidden"
        onChange={(e) => { onChange(e.target.files?.[0] || null); e.target.value = '' }} />
      {arquivo ? (
        <div className="flex items-center gap-3 h-10 px-3 rounded-md" style={{ backgroundColor: 'var(--color-primary-bg)' }}>
          <Icone size={16} style={{ color: 'var(--color-primary-text)' }} />
          <span className="text-sm truncate" style={{ color: 'var(--color-text)' }}>{arquivo.name}</span>
          <span className="text-meta tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>{tamanho(arquivo.size)}</span>
          <button type="button" disabled={desativado} onClick={() => onChange(null)} aria-label="Remover arquivo"
            className="ml-auto inline-flex items-center justify-center h-8 w-8 rounded-md cursor-pointer disabled:cursor-default" style={{ color: 'var(--color-text-secondary)' }}>
            <X size={16} />
          </button>
        </div>
      ) : (
        <button type="button" disabled={desativado} onClick={() => entrada.current?.click()}
          className="flex items-center gap-2 h-10 px-3 rounded-md text-sm cursor-pointer disabled:cursor-default"
          style={{ border: '1px dashed var(--color-border)', color: 'var(--color-text-secondary)' }}>
          <Paperclip size={16} /> Anexar PDF, planilha ou Word
        </button>
      )}
      {ajuda && <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{ajuda}</span>}
    </div>
  )
}

import Select from '../ui/Select'
import type { Executivo, Filtros } from '../../lib/mitra-api'
import { OPCOES_STATUS } from '../../lib/formatos'
import { PERIODOS } from '../../lib/periodo'
import { useSessao } from '../../lib/sessao'

interface Props {
  filtros: Filtros & { periodo: string }
  mudar: (f: Filtros & { periodo: string }) => void
  executivos: Executivo[]
  segmentos: string[]
}

export default function BarraFiltros({ filtros, mudar, executivos, segmentos }: Props) {
  const { admin } = useSessao()
  return (
    <>
      {admin && <div className="w-full sm:w-44">
        <Select label="Usuário" value={filtros.executivo} onChange={(v) => mudar({ ...filtros, executivo: v })}
          options={[{ value: '', label: 'Todos' }, ...executivos.map((e) => ({ value: String(e.id), label: e.nome }))]} />
      </div>}
      <div className="w-full sm:w-44">
        <Select label="Segmento" value={filtros.segmento} onChange={(v) => mudar({ ...filtros, segmento: v })}
          options={[{ value: '', label: 'Todos' }, ...segmentos.map((s) => ({ value: s, label: s }))]} />
      </div>
      <div className="w-full sm:w-44">
        <Select label="Status" value={filtros.status} onChange={(v) => mudar({ ...filtros, status: v })}
          options={[{ value: '', label: 'Todos' }, ...OPCOES_STATUS]} />
      </div>
      <div className="w-full sm:w-44">
        <Select label="Período" value={filtros.periodo} onChange={(v) => mudar({ ...filtros, periodo: v })} options={PERIODOS} />
      </div>
    </>
  )
}

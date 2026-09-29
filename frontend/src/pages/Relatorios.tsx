import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/ui/Card'
import { ChartContainer, ShadcnBarChart, ShadcnPieChart } from '../components/ui/Chart'
import BarraFiltros from '../components/app/Filtros'
import { Aviso, Esqueleto, Pagina, Vazio } from '../components/app/Pagina'
import { useApoio } from '../hooks/useApoio'
import { consultar, FILTROS_VAZIOS } from '../lib/mitra-api'
import type { LinhaRelatorio } from '../lib/mitra-api'
import { dolares, duracao, FONTE, PRECO, STATUS } from '../lib/formatos'
import type { Status } from '../lib/mitra-api'
import { intervalo } from '../lib/periodo'

const ROTULOS: Record<string, (v: string) => string> = {
  status: (v) => STATUS[v as Status]?.rotulo || v,
  fonte: (v) => FONTE[v] || v,
  preco: (v) => PRECO[v]?.rotulo || v,
  executivo: (v) => v, segmento: (v) => v, periodo: (v) => v,
}

function Tabela({ titulo, linhas, dim }: { titulo: string; linhas: LinhaRelatorio[]; dim: string }) {
  return (
    <Card className="p-5 flex flex-col gap-3">
      <h2 className="text-base font-semibold">{titulo}</h2>
      {linhas.length === 0 ? <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Sem dados.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
                <th className="px-3 py-3 font-medium">{titulo}</th>
                <th className="px-3 py-3 font-medium text-right">Pedidos</th>
                <th className="px-3 py-3 font-medium text-right">Concluídos</th>
                <th className="px-3 py-3 font-medium text-right">Falharam</th>
                <th className="px-3 py-3 font-medium text-right">Em curadoria</th>
                <th className="px-3 py-3 font-medium text-right">Precisa catálogo</th>
                <th className="px-3 py-3 font-medium text-right">Tempo médio</th>
                <th className="px-3 py-3 font-medium text-right">Produtos (média)</th>
                <th className="px-3 py-3 font-medium text-right">Custo IA</th>
              </tr>
            </thead>
            <tbody>
              {linhas.map((l) => (
                <tr key={l.valor} style={{ borderTop: '1px solid var(--color-border)' }}>
                  <td className="px-3 py-3 font-medium">{ROTULOS[dim](l.valor)}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{l.pedidos}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{l.concluidos}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{l.falharam}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{l.em_curadoria}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{l.precisa_catalogo}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{duracao(l.tempo_medio_s)}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{l.produtos_medio ?? '—'}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{dolares(l.custo_ia_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

export default function Relatorios() {
  const { executivos, segmentos } = useApoio()
  const [filtros, setFiltros] = useState({ ...FILTROS_VAZIOS, periodo: '30' })
  const [dados, setDados] = useState<LinhaRelatorio[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const versao = useRef(0)

  useEffect(() => {
    const v = ++versao.current
    const { desde, ate } = intervalo(filtros.periodo)
    consultar<LinhaRelatorio>('relatorio_pocs', { executivo: filtros.executivo, segmento: filtros.segmento, status: filtros.status, desde, ate })
      .then((r) => { if (v === versao.current) { setDados(r); setErro(null) } })
      .catch(() => { if (v === versao.current) setErro('Não foi possível carregar o relatório.') })
  }, [filtros])

  const por = useMemo(() => {
    const g: Record<string, LinhaRelatorio[]> = {}
    for (const l of dados || []) (g[l.dimensao] ||= []).push(l)
    return g
  }, [dados])
  const total = por.total?.[0]
  const num = (v: unknown) => Number(v || 0)

  return (
    <Pagina titulo="Relatórios" subtitulo="Portais criados por executivo, segmento, período, status, fonte do catálogo e situação do preço.">
      <div className="flex flex-wrap items-end gap-3">
        <BarraFiltros filtros={filtros} mudar={setFiltros} executivos={executivos} segmentos={segmentos} />
      </div>
      {erro && <Aviso tipo="danger" titulo={erro} />}
      {dados === null ? <Card><Esqueleto linhas={6} /></Card> : !total || num(total.pedidos) === 0 ? (
        <Card><Vazio titulo="Nenhum pedido no período" texto="Mude o período ou os filtros para ver os indicadores." /></Card>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {[
              ['Pedidos', String(total.pedidos)],
              ['Portais concluídos', `${total.concluidos} (${Math.round(100 * num(total.concluidos) / num(total.pedidos))}%)`],
              ['Tempo médio até o link', duracao(total.tempo_medio_s)],
              ['Custo total da IA', dolares(total.custo_ia_usd)],
            ].map(([k, v]) => (
              <Card key={k} className="p-5 flex flex-col gap-2">
                <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>{k}</span>
                <span className="text-2xl font-semibold tabular-nums">{v}</span>
              </Card>
            ))}
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            <ChartContainer title="Pedidos por mês" className="xl:col-span-2">
              <ShadcnBarChart data={(por.periodo || []).map((l) => ({ name: l.valor, Concluídos: num(l.concluidos), Outros: num(l.pedidos) - num(l.concluidos) }))}
                bars={[{ dataKey: 'Concluídos' }, { dataKey: 'Outros' }]} stacked />
            </ChartContainer>
            <ChartContainer title="Situação do preço">
              <ShadcnPieChart data={(por.preco || []).map((l) => ({ name: ROTULOS.preco(l.valor), value: num(l.pedidos) }))} />
            </ChartContainer>
          </div>
          <Tabela titulo="Executivo" dim="executivo" linhas={por.executivo || []} />
          <Tabela titulo="Segmento" dim="segmento" linhas={por.segmento || []} />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            <Tabela titulo="Status" dim="status" linhas={por.status || []} />
            <Tabela titulo="Fonte do catálogo" dim="fonte" linhas={por.fonte || []} />
          </div>
        </>
      )}
    </Pagina>
  )
}

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { Card } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import { Aviso, Esqueleto, Pagina, Vazio } from '../components/app/Pagina'
import { consultar } from '../lib/mitra-api'
import type { LinhaRelatorio, PedidoLinha } from '../lib/mitra-api'
import { dataHora, dolares, duracao, STATUS } from '../lib/formatos'

const num = (v: unknown) => Number(v) || 0

export default function Painel() {
  const [relatorio, setRelatorio] = useState<LinhaRelatorio[] | null>(null)
  const [portais, setPortais] = useState<PedidoLinha[] | null>(null)
  const [pendentes, setPendentes] = useState<PedidoLinha[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    let ativo = true
    const vazio = { executivo: '', segmento: '', desde: '', ate: '', busca: '', offset: '0' }
    Promise.allSettled([
      consultar<LinhaRelatorio>('relatorio_pocs', { executivo: '', segmento: '', status: '', desde: '', ate: '' }),
      consultar<PedidoLinha>('pedidos_listar', { ...vazio, status: 'concluido', limite: '12' }),
      consultar<PedidoLinha>('pedidos_listar', { ...vazio, status: 'curadoria', limite: '8' }),
    ]).then(([r, c, p]) => {
      if (!ativo) return
      if (r.status === 'fulfilled') setRelatorio(r.value); else setErro('Não foi possível carregar os indicadores.')
      setPortais(c.status === 'fulfilled' ? c.value : [])
      setPendentes(p.status === 'fulfilled' ? p.value : [])
    })
    return () => { ativo = false }
  }, [])

  const total = relatorio?.find((l) => l.dimensao === 'total')
  const usuarios = (relatorio || []).filter((l) => l.dimensao === 'executivo').sort((a, b) => num(b.pedidos) - num(a.pedidos))
  const kpis: [string, string, string][] = total ? [
    ['Pedidos', String(total.pedidos), `${total.em_andamento} em andamento`],
    ['Portais criados', String(total.concluidos), `${Math.round(100 * num(total.concluidos) / Math.max(1, num(total.pedidos)))}% dos pedidos`],
    ['Tempo médio até o link', duracao(total.tempo_medio_s), `criação: ${duracao(total.tempo_criacao_s)}`],
    ['Custo da IA', dolares(total.custo_ia_usd), `${total.falharam} falharam · ${total.precisa_catalogo} pediram catálogo`],
  ] : []

  return (
    <Pagina titulo="Painel do administrador" subtitulo="Visão geral dos portais de POC de todos os usuários.">
      {erro && <Aviso tipo="danger" titulo={erro} />}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {relatorio === null ? [0, 1, 2, 3].map((i) => <Card key={i} className="p-5"><Esqueleto linhas={2} /></Card>) : kpis.map(([rotulo, valor, detalhe]) => (
          <Card key={rotulo} className="p-5 flex flex-col gap-1">
            <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>{rotulo}</span>
            <span className="text-2xl font-semibold tabular-nums">{valor}</span>
            <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{detalhe}</span>
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card className="p-5 flex flex-col gap-3">
          <div className="flex items-center gap-3"><h2 className="text-base font-semibold">Portais criados</h2><Link to="/pedidos" className="ml-auto text-sm cursor-pointer" style={{ color: 'var(--color-primary-text)' }}>Ver todos</Link></div>
          {portais === null ? <Esqueleto linhas={4} /> : portais.length === 0 ? <Vazio titulo="Nenhum portal criado ainda" texto="Os portais aparecem aqui assim que um pedido é concluído." /> : (
            <div className="overflow-x-auto"><table className="w-full"><thead><tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
              <th className="px-3 py-3 font-medium">Cliente</th><th className="px-3 py-3 font-medium">Usuário</th><th className="px-3 py-3 font-medium">Concluído</th><th className="px-3 py-3" /></tr></thead>
              <tbody>{portais.map((p) => (
                <tr key={p.pedido_id} style={{ borderTop: '1px solid var(--color-border)' }}>
                  <td className="px-3 py-3"><Link to={`/pedidos/${p.pedido_id}`} className="font-medium cursor-pointer">{p.cliente}</Link></td>
                  <td className="px-3 py-3">{p.executivo}</td>
                  <td className="px-3 py-3 tabular-nums">{dataHora(p.concluido_em)}</td>
                  <td className="px-3 py-3 text-right">{p.portal_url && <a href={p.portal_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 cursor-pointer" style={{ color: 'var(--color-primary-text)' }}>Abrir <ExternalLink size={16} /></a>}</td>
                </tr>))}</tbody></table></div>
          )}
        </Card>
        <div className="flex flex-col gap-6">
          <Card className="p-5 flex flex-col gap-3">
            <h2 className="text-base font-semibold">Por usuário</h2>
            {relatorio === null ? <Esqueleto linhas={3} /> : usuarios.length === 0 ? <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Sem pedidos.</p> : (
              <div className="overflow-x-auto"><table className="w-full"><thead><tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
                <th className="px-3 py-3 font-medium">Usuário</th><th className="px-3 py-3 font-medium text-right">Pedidos</th><th className="px-3 py-3 font-medium text-right">Portais</th><th className="px-3 py-3 font-medium text-right">Tempo médio</th></tr></thead>
                <tbody>{usuarios.map((u) => (
                  <tr key={u.valor} style={{ borderTop: '1px solid var(--color-border)' }}>
                    <td className="px-3 py-3 font-medium">{u.valor}</td><td className="px-3 py-3 text-right tabular-nums">{u.pedidos}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{u.concluidos}</td><td className="px-3 py-3 text-right tabular-nums">{duracao(u.tempo_medio_s)}</td>
                  </tr>))}</tbody></table></div>
            )}
          </Card>
          <Card className="p-5 flex flex-col gap-3">
            <h2 className="text-base font-semibold">Aguardando curadoria</h2>
            {pendentes === null ? <Esqueleto linhas={3} /> : pendentes.length === 0 ? <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Nenhum pedido parado na curadoria.</p> : (
              <div className="flex flex-col">{pendentes.map((p) => (
                <Link key={p.pedido_id} to={`/pedidos/${p.pedido_id}`} className="flex items-center gap-3 py-3 cursor-pointer" style={{ borderTop: '1px solid var(--color-border)' }}>
                  <div className="leading-tight"><div className="font-medium">{p.cliente}</div><div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{p.executivo} · {dataHora(p.criado_em)}</div></div>
                  <span className="ml-auto"><Badge variant={STATUS[p.status].variante}>{p.produtos ?? 0} produtos</Badge></span>
                </Link>))}</div>
            )}
          </Card>
        </div>
      </div>
    </Pagina>
  )
}

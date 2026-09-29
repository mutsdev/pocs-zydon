import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ExternalLink, PlusCircle, RefreshCw, Search } from 'lucide-react'
import { Card } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import BarraFiltros from '../components/app/Filtros'
import { Aviso, Esqueleto, Pagina, Vazio } from '../components/app/Pagina'
import { useApoio } from '../hooks/useApoio'
import { consultar, FILTROS_VAZIOS } from '../lib/mitra-api'
import type { PedidoLinha } from '../lib/mitra-api'
import { dataHora, FONTE, PRECO, STATUS } from '../lib/formatos'
import { intervalo } from '../lib/periodo'

const PAGINA = 30

export default function Pedidos() {
  const { executivos, segmentos } = useApoio()
  const navegar = useNavigate()
  const [filtros, setFiltros] = useState({ ...FILTROS_VAZIOS, periodo: '' })
  const [busca, setBusca] = useState('')
  const [buscaAtiva, setBuscaAtiva] = useState('')
  const [linhas, setLinhas] = useState<PedidoLinha[] | null>(null)
  const [fim, setFim] = useState(false)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const versao = useRef(0)
  const sentinela = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const t = setTimeout(() => setBuscaAtiva(busca.trim()), 300)
    return () => clearTimeout(t)
  }, [busca])

  const carregar = useCallback(async (offset: number) => {
    const v = offset === 0 ? ++versao.current : versao.current
    setCarregando(true)
    try {
      const { desde, ate } = intervalo(filtros.periodo)
      const r = await consultar<PedidoLinha>('pedidos_listar', {
        executivo: filtros.executivo, segmento: filtros.segmento, status: filtros.status, desde, ate,
        busca: buscaAtiva, limite: String(PAGINA), offset: String(offset),
      })
      if (v !== versao.current) return
      setLinhas((atual) => (offset === 0 ? r : [...(atual || []), ...r]))
      setFim(r.length < PAGINA)
      setErro(null)
    } catch {
      if (v === versao.current) setErro('Não foi possível carregar os pedidos.')
    } finally {
      if (v === versao.current) setCarregando(false)
    }
  }, [filtros, buscaAtiva])

  useEffect(() => { carregar(0) }, [carregar])

  useEffect(() => {
    const alvo = sentinela.current
    if (!alvo) return
    const obs = new IntersectionObserver((e) => {
      if (e[0].isIntersecting && !carregando && !fim && linhas && linhas.length) carregar(linhas.length)
    })
    obs.observe(alvo)
    return () => obs.disconnect()
  }, [carregar, carregando, fim, linhas])

  return (
    <Pagina titulo="Pedidos" subtitulo="Todos os portais de POC, do pedido ao link."
      acao={<Button onClick={() => navegar('/novo')}><PlusCircle size={16} /> Novo pedido</Button>}>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-64">
          <Input label="Cliente" placeholder="Buscar cliente" value={busca} onChange={(e) => setBusca(e.target.value)} />
        </div>
        <BarraFiltros filtros={filtros} mudar={setFiltros} executivos={executivos} segmentos={segmentos} />
        <Button variant="secondary" className="ml-auto h-10" onClick={() => carregar(0)}><RefreshCw size={16} /> Atualizar</Button>
      </div>
      {erro && <Aviso tipo="danger" titulo={erro} />}
      <Card>
        {linhas === null ? <Esqueleto linhas={6} /> : linhas.length === 0 ? (
          <Vazio titulo="Nenhum pedido encontrado" texto={buscaAtiva || filtros.executivo || filtros.status || filtros.segmento || filtros.periodo
            ? 'Nenhum pedido com esses filtros. Limpe os filtros para ver todos.' : 'Abra o primeiro pedido com o nome do cliente e o site.'}
            acao={<Button onClick={() => navegar('/novo')}><PlusCircle size={16} /> Novo pedido</Button>} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
                  <th className="px-3 py-3 font-medium">Cliente</th>
                  <th className="px-3 py-3 font-medium">Usuário</th>
                  <th className="px-3 py-3 font-medium">Segmento</th>
                  <th className="px-3 py-3 font-medium text-right">Produtos</th>
                  <th className="px-3 py-3 font-medium">Preço</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  <th className="px-3 py-3 font-medium">Portal</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map((p) => (
                  <tr key={p.pedido_id} className="cursor-pointer transition-colors hover:bg-[var(--color-nav-hover)]"
                    style={{ borderTop: '1px solid var(--color-border)' }} onClick={() => navegar(`/pedidos/${p.pedido_id}`)}>
                    <td className="px-3 py-3">
                      <div className="leading-tight">
                        <div className="font-medium" style={{ color: 'var(--color-text)' }}>{p.cliente}</div>
                        <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{p.pedido_id} · {dataHora(p.criado_em)}</div>
                      </div>
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap">{p.executivo}</td>
                    <td className="px-3 py-3">
                      <div className="leading-tight">
                        <div>{p.segmento || '—'}</div>
                        {p.segmento_origem === 'inferido' && <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>inferido</div>}
                      </div>
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">
                      <div className="leading-tight">
                        <div>{p.produtos ?? '—'}</div>
                        {p.fonte && <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{FONTE[p.fonte] || p.fonte}</div>}
                      </div>
                    </td>
                    <td className="px-3 py-3">{p.preco ? <Badge variant={PRECO[p.preco]?.variante || 'neutral'}>{PRECO[p.preco]?.rotulo || p.preco}</Badge> : '—'}</td>
                    <td className="px-3 py-3 whitespace-nowrap">
                      <Badge variant={STATUS[p.status].variante} dot={p.em_execucao}>{STATUS[p.status].rotulo}</Badge>
                    </td>
                    <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                      {p.portal_url ? (
                        <a href={p.portal_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm cursor-pointer" style={{ color: 'var(--color-primary-text)' }}>
                          Abrir <ExternalLink size={14} />
                        </a>
                      ) : <Link to={`/pedidos/${p.pedido_id}`} className="text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>Ver</Link>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div ref={sentinela} className="h-4" />
            {carregando && linhas.length > 0 && <div className="flex justify-center py-3"><Search size={16} className="animate-pulse" style={{ color: 'var(--color-text-secondary)' }} /></div>}
          </div>
        )}
      </Card>
    </Pagina>
  )
}

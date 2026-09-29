import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink, FileText, FlaskConical, ImageOff, ImageUp, Loader2, RefreshCw, Rocket, Save, Wand2 } from 'lucide-react'
import { Card } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Checkbox from '../components/ui/Checkbox'
import Input from '../components/ui/Input'
import { ToastContainer } from '../components/ui/Toast'
import { useToast } from '../hooks/useToast'
import { Aviso, Esqueleto, Pagina } from '../components/app/Pagina'
import Espera from '../components/app/Espera'
import CampoAnexo from '../components/app/CampoAnexo'
import { enviarAnexo, enviarLogo, validarArquivo, validarLogo, ACEITOS_LOGO } from '../lib/anexo'
import { acionar, consultar, ErroApi } from '../lib/mitra-api'
import type { Evento, Pedido, Peca } from '../lib/mitra-api'
import { useSessao } from '../lib/sessao'
import { BANNERS, dataHora, dolares, FONTE, PRECO, reais, STATUS } from '../lib/formatos'

interface PrecoResumo { sku: string; nome: string; origem: string; regra: string; preco: number | null; origem_url?: string; imagem?: string; do_cliente?: boolean }
interface Requisicao { label: string; temp_image_url?: string; _origem_url?: string; _miniatura?: string; _preco_estimado?: boolean; payload: { sku: string; name: string; price: number | null; description?: string } }
interface Catalogo { etapas: { endpoint: string; requests: Requisicao[] }[]; [k: string]: unknown }
interface Resumo { precos?: PrecoResumo[]; regra_preco_estimado?: string | null; produtos_similares?: boolean; descartes?: { nome: string; motivo: string }[]; [k: string]: unknown }

const MINIMO = 5
const ORIGEM_LOGO: Record<string, string> = { site: 'Achada no site do cliente.', web: 'Achada na web, fora do site informado: confira.', texto: 'Gerada a partir do nome do cliente (texto), porque nenhuma logo foi achada.', enviada: 'Enviada pelo usuário.' }
const json = <T,>(t: string | null): T | null => { try { return t ? JSON.parse(t) as T : null } catch { return null } }

function situacao(precos: PrecoResumo[]) {
  if (!precos.length || !precos.some((p) => p.preco)) return 'ausente'
  return precos.every((p) => p.origem === 'publico') ? 'publico' : 'estimado'
}

function Miniatura({ src }: { src?: string }) {
  const [falhou, setFalhou] = useState(false)
  if (!src || falhou) {
    return <div className="h-12 w-12 rounded-md flex items-center justify-center shrink-0" title="Imagem indisponível" style={{ backgroundColor: 'var(--color-bg)', color: 'var(--color-text-secondary)' }}><ImageOff size={18} /></div>
  }
  return <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFalhou(true)} className="h-12 w-12 rounded-md object-contain shrink-0" style={{ backgroundColor: 'var(--color-bg)' }} />
}

function Origem({ url }: { url?: string }) {
  if (!url) return null
  if (url.startsWith('anexo:')) {
    const [arquivo, trecho = ''] = url.slice(6).split('#')
    const onde = trecho.replace('pagina=', 'página ').replace('linha=', 'linha ').replace('tabela=', 'tabela ').replace('&', ', ').replace('paragrafo=', 'parágrafo ')
    return <span className="inline-flex items-center gap-1" title={arquivo}><FileText size={12} /> anexo{onde ? ` · ${onde}` : ''}</span>
  }
  if (!/^https?:\/\//i.test(url)) return null
  return <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 cursor-pointer" style={{ color: 'var(--color-primary-text)' }}>origem <ExternalLink size={12} /></a>
}

export default function PedidoDetalhe() {
  const { id = '' } = useParams()
  const { toasts, addToast, removeToast } = useToast()
  const sessao = useSessao()
  const [pedido, setPedido] = useState<Pedido | null>(null)
  const [eventos, setEventos] = useState<Evento[]>([])
  const [pecas, setPecas] = useState<Peca[]>([])
  const [erro, setErro] = useState<string | null>(null)
  const [atualizando, setAtualizando] = useState(false)
  const [ocupado, setOcupado] = useState<string | null>(null)
  const [excluidos, setExcluidos] = useState<Set<string>>(new Set())
  const [edicoes, setEdicoes] = useState<Record<string, { nome?: string; preco?: string }>>({})
  const [feedback, setFeedback] = useState('')

  const local = useLocation()
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [progresso, setProgresso] = useState<number | null>(null)
  const statusAnterior = useRef<string | null>(null)
  const entradaLogo = useRef<HTMLInputElement>(null)
  const [progressoLogo, setProgressoLogo] = useState<number | null>(null)

  const carregar = useCallback(async (silencioso = false) => {
    if (!silencioso) setAtualizando(true)
    const [p, e, b] = await Promise.allSettled([
      consultar<Pedido>('pedido_ler', { pedido_id: id }),
      consultar<Evento>('pedido_eventos', { pedido_id: id }),
      consultar<Peca>('pedido_pecas', { pedido_id: id }),
    ])
    if (p.status === 'fulfilled') {
      if (!p.value.length) setErro('Pedido não encontrado.')
      else { setPedido(p.value[0]); setErro(null) }
    } else setErro('Não foi possível carregar o pedido.')
    if (e.status === 'fulfilled') setEventos(e.value)
    if (b.status === 'fulfilled') setPecas(b.value)
    setAtualizando(false)
  }, [id])

  useEffect(() => { carregar() }, [carregar])

  useEffect(() => {
    const aviso = (local.state as { aviso?: string } | null)?.aviso
    if (aviso) addToast('error', aviso)
  }, [local.state, addToast])

  const emAndamento = !!pedido && (['extraindo', 'criando', 'aguardando_anexo'].includes(pedido.status) || pedido.em_execucao
    || ['gerando', 'regerando', 'aplicando'].includes(pedido.banners_situacao || ''))
  useEffect(() => {
    if (!emAndamento) return
    const relogio = setTimeout(() => { if (document.visibilityState === 'visible') carregar(true); else setAtualizando(false) }, 4000)
    return () => clearTimeout(relogio)
  }, [emAndamento, pedido, carregar])

  useEffect(() => {
    if (!pedido) return
    const antes = statusAnterior.current
    statusAnterior.current = pedido.status
    if (!antes || antes === pedido.status) return
    const rotulos: Record<string, ['success' | 'error', string]> = {
      curadoria: ['success', 'Produtos prontos para a curadoria.'],
      concluido: ['success', 'Portal criado. O link já está no card Portal.'],
      falhou: ['error', 'O pedido falhou. Veja o motivo abaixo.'],
      precisa_catalogo: ['error', 'O site não teve produtos suficientes: anexe o catálogo.'],
    }
    const r = rotulos[pedido.status]
    if (r) addToast(r[0], r[1])
  }, [pedido, addToast])

  async function enviarCatalogo() {
    if (!arquivo) return
    const problema = validarArquivo(arquivo)
    if (problema) { addToast('error', problema); return }
    setOcupado('anexo')
    setProgresso(0)
    try {
      await enviarAnexo(id, arquivo, setProgresso)
      setArquivo(null)
      addToast('success', 'Catálogo recebido. Lendo os produtos…')
      await carregar(true)
    } catch (e) {
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível enviar o arquivo.')
    } finally {
      setOcupado(null)
      setProgresso(null)
    }
  }

  async function trocarLogo(novo: File | null) {
    if (!novo) return
    const problema = validarLogo(novo)
    if (problema) { addToast('error', problema); return }
    setOcupado('logo')
    setProgressoLogo(0)
    try {
      await enviarLogo(id, novo, setProgressoLogo)
      addToast('success', 'Logo recebida. Conferindo e refazendo os banners…')
      await carregar(true)
    } catch (e) {
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível enviar a logo.')
    } finally {
      setOcupado(null)
      setProgressoLogo(null)
    }
  }

  const catalogo = useMemo(() => json<Catalogo>(pedido?.catalogo ?? null), [pedido?.catalogo])
  const resumo = useMemo(() => json<Resumo>(pedido?.resumo ?? null) || {}, [pedido?.resumo])
  const produtos = useMemo(() => catalogo?.etapas.find((e) => e.endpoint === 'products')?.requests || [], [catalogo])
  const precoPorSku = useMemo(() => Object.fromEntries((resumo.precos || []).map((p) => [p.sku, p])), [resumo])
  const emCuradoria = pedido?.status === 'curadoria' && !pedido.portal_id
  const restantes = produtos.length - excluidos.size
  const alterado = excluidos.size > 0 || Object.keys(edicoes).length > 0
  const geracao = pecas.length ? Math.max(...pecas.map((x) => x.geracao)) : 0
  const pecasAtuais = pecas.filter((x) => x.geracao === geracao)

  async function executar(rotulo: string, entrada: Record<string, unknown>, sucesso: string) {
    setOcupado(rotulo)
    try {
      await acionar('pedido_acao', { pedido_id: id, ...entrada })
      addToast('success', sucesso)
      if (entrada.acao === 'extrair') setPedido((atual) => (atual ? { ...atual, status: 'extraindo', acao_desde: new Date().toISOString() } : atual))
      await carregar(true)
    } catch (e) {
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível executar a ação.')
    } finally {
      setOcupado(null)
    }
  }

  async function salvarCuradoria(): Promise<boolean> {
    if (!catalogo || !pedido) return false
    if (restantes < MINIMO) { addToast('error', `Mantenha pelo menos ${MINIMO} produtos.`); return false }
    const novo: Catalogo = JSON.parse(JSON.stringify(catalogo))
    const etapa = novo.etapas.find((e) => e.endpoint === 'products')!
    const precos: PrecoResumo[] = []
    etapa.requests = etapa.requests.filter((r) => !excluidos.has(r.payload.sku)).map((r) => {
      const ed = edicoes[r.payload.sku] || {}
      const base = precoPorSku[r.payload.sku]
      const entrada: PrecoResumo = base ? { ...base } : { sku: r.payload.sku, nome: r.payload.name, origem: 'estimado', regra: '', preco: r.payload.price }
      if (ed.nome !== undefined && ed.nome.trim()) { r.payload.name = ed.nome.trim(); r.label = `${r.payload.sku} — ${r.payload.name}`; entrada.nome = r.payload.name }
      if (ed.preco !== undefined) {
        const valor = Number(ed.preco.replace(/\./g, '').replace(',', '.'))
        if (Number.isFinite(valor) && valor > 0) {
          r.payload.price = valor
          entrada.preco = valor
          entrada.origem = 'estimado'
          entrada.regra = 'informado pelo usuário na curadoria'
          r._preco_estimado = true
        }
      }
      precos.push(entrada)
      return r
    })
    const novoResumo = { ...resumo, precos, produtos: precos.length, preco: situacao(precos) }
    const anterior = pedido
    setPedido({ ...pedido, catalogo: JSON.stringify(novo), resumo: JSON.stringify(novoResumo), produtos: precos.length, preco: novoResumo.preco })
    setExcluidos(new Set()); setEdicoes({})
    try {
      const r = await consultar('curadoria_salvar', {
        pedido_id: id, catalogo: JSON.stringify(novo), resumo: JSON.stringify(novoResumo),
        produtos: String(precos.length), preco: novoResumo.preco,
      })
      if (!r.length) throw new Error('não gravou')
      return true
    } catch {
      setPedido(anterior)
      addToast('error', 'Não foi possível salvar a curadoria.')
      return false
    }
  }

  async function criarPortal(simular: boolean) {
    if (alterado && !(await salvarCuradoria())) return
    if (simular) {
      await executar('simular', { acao: 'criar', simular: true }, 'Simulação enviada. Veja o resultado na linha do tempo.')
      return
    }
    const anterior = pedido
    const agora = new Date().toISOString()
    if (pedido) setPedido({ ...pedido, status: 'criando', acao_desde: agora, criacao_inicio: agora })
    setOcupado('criar')
    try {
      await acionar('pedido_acao', { pedido_id: id, acao: 'criar', simular: false })
      await carregar(true)
    } catch (e) {
      if (e instanceof ErroApi && e.codigo === 'STATUS_NAO_PERMITE') {
        await carregar(true)
      } else {
        if (anterior) setPedido(anterior)
        addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível criar o portal.')
      }
    } finally {
      setOcupado(null)
    }
  }

  if (erro && !pedido) return <Pagina titulo="Pedido"><Aviso tipo="danger" titulo={erro} /></Pagina>
  if (!pedido) return <Pagina titulo="Pedido"><Card><Esqueleto linhas={8} /></Card></Pagina>

  const st = STATUS[pedido.status]
  return (
    <Pagina titulo={pedido.cliente} subtitulo={`${pedido.pedido_id} · ${pedido.executivo} · aberto em ${dataHora(pedido.criado_em)}`}
      acao={<>
        <Link to="/pedidos"><Button variant="ghost"><ArrowLeft size={16} /> Pedidos</Button></Link>
        <Button variant="secondary" onClick={() => carregar()} disabled={atualizando}>
          {atualizando ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />} Atualizar
        </Button>
      </>}>
      <ToastContainer toasts={toasts} onRemove={removeToast} />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <Card className="p-5 flex flex-col gap-2">
          <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>Status</span>
          <div className="flex items-center gap-2"><Badge variant={st.variante} dot={pedido.em_execucao}>{st.rotulo}</Badge>{pedido.simulado && <Badge variant="neutral">simulado</Badge>}</div>
          {pedido.em_execucao && <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Em andamento: {pedido.execucao_acao}</span>}
        </Card>
        <Card className="p-5 flex flex-col gap-2">
          <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>Catálogo</span>
          <span className="text-base font-semibold">{pedido.produtos ?? '—'} produtos · {pedido.categorias ?? '—'} categorias</span>
          <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Fonte: {pedido.fonte ? FONTE[pedido.fonte] || pedido.fonte : '—'}</span>
        </Card>
        <Card className="p-5 flex flex-col gap-2">
          <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>Segmento</span>
          <span className="text-base font-semibold">{pedido.segmento || '—'}</span>
          <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{pedido.segmento_origem === 'inferido' ? 'inferido pelo sistema' : pedido.segmento_origem === 'informado' ? 'informado pelo usuário' : '—'}</span>
          {pedido.foco && <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Foco: {pedido.foco}</span>}
        </Card>
        <Card className="p-5 flex flex-col gap-2">
          <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>Portal</span>
          {pedido.portal_url ? (
            <a href={pedido.portal_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 font-semibold cursor-pointer break-all" style={{ color: 'var(--color-primary-text)' }}>
              Abrir portal <ExternalLink size={16} />
            </a>
          ) : <span className="text-base font-semibold">Ainda não criado</span>}
          <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{BANNERS[pedido.banners_situacao || ''] || 'Banners pendentes'}</span>
        </Card>
      </div>

      {pedido.status === 'falhou' && (
        <Aviso tipo="danger" titulo={pedido.erro_codigo === 'SEM_CREDITO_IA' ? 'A busca parou por falta de crédito na IA de seleção' : 'O pedido falhou'}>
          {pedido.erro || 'Veja a linha do tempo para o detalhe.'}
          <div className="mt-2"><Button size="sm" variant="secondary" disabled={!!ocupado} onClick={() => executar('extrair', { acao: 'extrair' }, 'Nova busca iniciada.')}>Tentar de novo</Button></div>
        </Aviso>
      )}
      {pedido.status === 'precisa_catalogo' && (
        <Aviso titulo="Precisamos do catálogo do cliente em PDF, planilha ou Word">
          {pedido.motivo_catalogo}
          <div className="mt-3 flex flex-col gap-3 max-w-xl">
            <CampoAnexo arquivo={arquivo} onChange={setArquivo} rotulo="Catálogo do cliente" desativado={!!ocupado} />
            <div className="flex flex-wrap items-center gap-3">
              <Button size="sm" disabled={!arquivo || !!ocupado} onClick={enviarCatalogo}>
                {progresso !== null ? <><Loader2 size={16} className="animate-spin" /> Enviando {Math.round(progresso * 100)}%</> : 'Enviar e ler o catálogo'}
              </Button>
              <Button size="sm" variant="secondary" disabled={!!ocupado} onClick={() => executar('extrair', { acao: 'extrair' }, 'Nova busca iniciada.')}>Buscar de novo no site</Button>
            </div>
          </div>
        </Aviso>
      )}
      {pedido.status === 'aguardando_anexo' && !pedido.em_execucao && (
        <Aviso titulo="O anexo não terminou de chegar">
          Envie o arquivo de novo para o sistema ler o catálogo.
          <div className="mt-3 flex flex-col gap-3 max-w-xl">
            <CampoAnexo arquivo={arquivo} onChange={setArquivo} rotulo="Catálogo do cliente" desativado={!!ocupado} />
            <div><Button size="sm" disabled={!arquivo || !!ocupado} onClick={enviarCatalogo}>
              {progresso !== null ? `Enviando ${Math.round(progresso * 100)}%` : 'Enviar e ler o catálogo'}
            </Button></div>
          </div>
        </Aviso>
      )}
      {(pedido.status === 'extraindo' || pedido.status === 'criando' || (pedido.status === 'aguardando_anexo' && pedido.em_execucao)) && (
        <Espera
          titulo={pedido.status === 'criando' ? 'Criando o portal na Zydon' : pedido.anexo_nome ? `Lendo o catálogo ${pedido.anexo_nome}` : 'Buscando os produtos do cliente'}
          mensagem={eventos[0]?.mensagem || (pedido.status === 'criando' ? 'Um portal por vez; se houver outro na fila, este espera a vez.' : 'A tela se atualiza sozinha.')}
          desde={pedido.status === 'criando' ? (pedido.acao_desde || pedido.criacao_inicio) : (pedido.acao_desde || pedido.criado_em)} />
      )}
      {pedido.status !== 'extraindo' && pedido.status !== 'criando' && ['gerando', 'regerando', 'aplicando'].includes(pedido.banners_situacao || '') && (
        <Espera titulo={pedido.execucao_acao === 'trocar_logo' ? 'Trocando a logo e refazendo os banners' : 'Gerando os banners de identidade visual'} mensagem={eventos[0]?.mensagem || 'A tela se atualiza sozinha quando terminar.'} desde={pedido.acao_desde || pedido.execucao_desde} />
      )}
      {(pedido.nomes_lidos_na_imagem || 0) > 0 && (
        <Aviso titulo={`${pedido.nomes_lidos_na_imagem} nomes de produto foram lidos nas fotos do site`}>O site não tinha o nome em texto; o sistema leu o que está escrito na foto. Confira cada nome antes de criar o portal.</Aviso>
      )}
      {pedido.produtos_similares && <Aviso titulo="Há produtos que NÃO são da marca do cliente">A busca trouxe produtos similares do segmento. Eles estão marcados na lista; confirme com o cliente antes de mostrar.</Aviso>}
      {pedido.preco && pedido.preco !== 'publico' && (
        <Aviso titulo={pedido.preco === 'ausente' ? 'Nenhum produto tem preço' : 'Há preços estimados neste catálogo'}>
          {resumo.regra_preco_estimado || 'Os preços marcados como estimados não vieram do site do cliente.'}
        </Aviso>
      )}

      {produtos.length > 0 && (
        <Card>
          <div className="flex flex-wrap items-end gap-3 p-5">
            <div className="flex flex-col gap-1">
              <h2 className="text-base font-semibold">Curadoria dos produtos</h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {emCuradoria ? `Desmarque o que não deve ir para o portal e ajuste nome ou preço. ${restantes} de ${produtos.length} selecionados.` : 'O catálogo já foi enviado.'}
              </p>
            </div>
            {emCuradoria && (
              <div className="ml-auto flex flex-wrap gap-2">
                <Button variant="secondary" disabled={!alterado || !!ocupado} onClick={async () => { if (await salvarCuradoria()) addToast('success', 'Curadoria salva.') }}><Save size={16} /> Salvar</Button>
                <Button variant="secondary" disabled={!!ocupado || pedido.em_execucao} onClick={() => criarPortal(true)}>
                  {ocupado === 'simular' ? <Loader2 size={16} className="animate-spin" /> : <FlaskConical size={16} />} Simular
                </Button>
                <Button disabled={!!ocupado || pedido.em_execucao || restantes < MINIMO} onClick={() => criarPortal(false)}>
                  {ocupado === 'criar' ? <Loader2 size={16} className="animate-spin" /> : <Rocket size={16} />} Aprovar e criar portal
                </Button>
              </div>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
                  {emCuradoria && <th className="px-3 py-3 w-10" />}
                  <th className="px-3 py-3 font-medium">Produto</th>
                  <th className="px-3 py-3 font-medium text-right">Preço</th>
                  <th className="px-3 py-3 font-medium">Origem do preço</th>
                </tr>
              </thead>
              <tbody>
                {produtos.map((r) => {
                  const sku = r.payload.sku
                  const info = precoPorSku[sku]
                  const fora = excluidos.has(sku)
                  const estimado = info ? info.origem !== 'publico' : !!r._preco_estimado
                  return (
                    <tr key={sku} style={{ borderTop: '1px solid var(--color-border)', opacity: fora ? 0.45 : 1 }}>
                      {emCuradoria && (
                        <td className="px-3 py-3">
                          <Checkbox checked={!fora} onChange={(v) => setExcluidos((s) => { const n = new Set(s); if (v) n.delete(sku); else n.add(sku); return n })} />
                        </td>
                      )}
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-3 min-w-64">
                          <Miniatura src={r._miniatura || r.temp_image_url} />
                          <div className="flex flex-col gap-1 w-full">
                            {emCuradoria ? (
                              <Input value={edicoes[sku]?.nome ?? r.payload.name} onChange={(e) => setEdicoes((s) => ({ ...s, [sku]: { ...s[sku], nome: e.target.value } }))} />
                            ) : <span className="font-medium">{r.payload.name}</span>}
                            <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                              <span>{sku}</span>
                              <Origem url={r._origem_url || info?.origem_url} />
                              {info?.do_cliente === false && <Badge variant="warning">outra marca</Badge>}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {emCuradoria ? (
                          <div className="w-32 ml-auto"><Input className="text-right" value={edicoes[sku]?.preco ?? (r.payload.price ? String(r.payload.price).replace('.', ',') : '')}
                            onChange={(e) => setEdicoes((s) => ({ ...s, [sku]: { ...s[sku], preco: e.target.value } }))} /></div>
                        ) : reais(r.payload.price)}
                      </td>
                      <td className="px-3 py-3">
                        <div className="leading-tight">
                          <Badge variant={estimado ? 'warning' : 'success'}>{estimado ? 'Estimado' : 'Público'}</Badge>
                          {info?.regra && <div className="text-sm mt-1 max-w-sm" style={{ color: 'var(--color-text-secondary)' }}>{info.regra}</div>}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {(pedido.status === 'curadoria' || pedido.status === 'concluido') && (
        <Card className="p-5 flex flex-col gap-3">
          <div className="flex flex-wrap items-start gap-3">
            <div className="flex flex-col gap-1">
              <h2 className="text-base font-semibold">Logo do cliente</h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {ORIGEM_LOGO[pedido.logo_origem || ''] || 'Nenhuma logo encontrada.'} Se estiver errada, envie a logo certa: os banners são refeitos{pedido.portal_id ? ' e o portal recebe a logo nova' : ''}.
              </p>
            </div>
            <input ref={entradaLogo} type="file" accept={ACEITOS_LOGO} className="hidden"
              onChange={(e) => { const f = e.target.files?.[0] || null; e.target.value = ''; trocarLogo(f) }} />
            <Button size="sm" variant="secondary" className="ml-auto" disabled={!!ocupado || pedido.em_execucao} onClick={() => entradaLogo.current?.click()}>
              {progressoLogo !== null ? <><Loader2 size={16} className="animate-spin" /> Enviando {Math.round(progressoLogo * 100)}%</> : <><ImageUp size={16} /> {pedido.logo_previa ? 'Trocar logo' : 'Enviar logo'}</>}
            </Button>
          </div>
          {pedido.logo_aviso && <p className="text-sm" style={{ color: 'var(--color-warning)' }}>{pedido.logo_aviso}</p>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {[{ nome: 'Sobre fundo claro', fundo: '#ffffff' }, { nome: 'Sobre fundo escuro', fundo: '#1c1c1e' }].map((f) => (
              <div key={f.nome} className="flex flex-col gap-1.5">
                <span className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>{f.nome}</span>
                <div className="h-28 rounded-md flex items-center justify-center p-4" style={{ backgroundColor: f.fundo }}>
                  {pedido.logo_previa
                    ? <img src={`data:image/png;base64,${pedido.logo_previa}`} alt={`Logo de ${pedido.cliente}`} className="max-h-full max-w-full object-contain" />
                    : <ImageOff size={24} style={{ color: '#8a8a8a' }} />}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
      {(pecasAtuais.length > 0 || pedido.banners_situacao) && (
        <Card className="p-5 flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <h2 className="text-base font-semibold">Banners</h2>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{BANNERS[pedido.banners_situacao || ''] || '—'}{pedido.banner_cor ? ` · cor ${pedido.banner_cor}` : ''}</p>
            </div>
            {pedido.banners_situacao !== 'dispensado' && pedido.banners_situacao !== 'sem_banner' && (
              <div className="ml-auto flex flex-wrap gap-2">
                <Button variant="ghost" disabled={!!ocupado || pedido.em_execucao} onClick={() => executar('dispensar', { acao: 'banner', acao_banner: 'dispensar' }, 'Banners dispensados.')}>Dispensar</Button>
                {pedido.portal_id && pecasAtuais.some((x) => x.file_id) && !pecasAtuais.every((x) => x.aplicada) && (
                  <Button disabled={!!ocupado || pedido.em_execucao} onClick={() => executar('aplicar', {
                    acao: 'banner', acao_banner: 'aplicar',
                    escolhas: Object.fromEntries(pecasAtuais.filter((x) => x.file_id).map((x) => [x.peca, x.file_id])),
                  }, 'Trocando os banners do portal; a conferência é feita lendo o portal.')}>
                    {ocupado === 'aplicar' ? <Loader2 size={16} className="animate-spin" /> : <Rocket size={16} />} {pecas.some((x) => x.aplicada) ? 'Alterar os do portal' : 'Aplicar no portal'}
                  </Button>
                )}
              </div>
            )}
          </div>
          {pecasAtuais.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {pecasAtuais.map((x) => (
                <div key={x.id} className="flex flex-col gap-2">
                  {x.previa_base64 ? <img src={`data:${x.previa_base64.startsWith("iVBOR") ? "image/png" : "image/jpeg"};base64,${x.previa_base64}`} alt={x.peca} className="w-full rounded-md" /> :
                    <div className="h-32 rounded-md flex items-center justify-center" style={{ backgroundColor: 'var(--color-bg)' }}><ImageOff size={20} /></div>}
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">{x.peca}</span>
                    <span style={{ color: 'var(--color-text-secondary)' }}>geração {x.geracao}</span>
                    {x.aplicada && <Badge variant={x.conferida_get ? 'success' : 'danger'}>{x.conferida_get ? 'aplicada e conferida' : 'não confirmada no portal'}</Badge>}
                  </div>
                </div>
              ))}
            </div>
          )}
          {pecasAtuais.length > 0 && pedido.banners_situacao !== 'dispensado' && (
            <div className="flex flex-wrap items-end gap-3">
              <div className="w-full sm:w-96"><Input label="O que mudar nos banners" placeholder="Ex.: fundo mais claro, sem pessoas" value={feedback} onChange={(e) => setFeedback(e.target.value)} /></div>
              <Button variant="secondary" className="h-10" disabled={!!ocupado || pedido.em_execucao}
                onClick={() => executar('regerar', { acao: 'banner', acao_banner: 'regerar', feedback, pecas: pecasAtuais.map((x) => x.peca) }, 'Novos banners em geração.')}>
                {ocupado === 'regerar' ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />} Refazer banners
              </Button>
            </div>
          )}
        </Card>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {sessao.admin && <Card className="p-5 flex flex-col gap-3 xl:col-span-2">
          <h2 className="text-base font-semibold">Linha do tempo</h2>
          {eventos.length === 0 ? <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Sem eventos ainda.</p> : (
            <ul className="flex flex-col">
              {eventos.map((e) => (
                <li key={e.id} className="flex gap-3 py-2" style={{ borderTop: '1px solid var(--color-border)' }}>
                  <span className="text-meta whitespace-nowrap pt-0.5" style={{ color: 'var(--color-text-secondary)' }}>{dataHora(e.criado_em)}</span>
                  <span className="text-sm" style={{ color: e.nivel === 'erro' ? 'var(--color-danger)' : e.nivel === 'aviso' ? 'var(--color-warning)' : 'var(--color-text)' }}>
                    <b className="font-medium">{e.etapa}</b> · {e.mensagem}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>}
        <Card className="p-5 flex flex-col gap-3">
          <h2 className="text-base font-semibold">Rastreio</h2>
          <dl className="grid grid-cols-1 gap-2 text-sm">
            {[
              ['Site', pedido.site], ['Preço', pedido.preco ? PRECO[pedido.preco]?.rotulo || pedido.preco : '—'],
              ['Modelo de IA', pedido.modelo_ia || '—'], ['Custo da IA', dolares(pedido.custo_ia_usd)],
              ['Tokens', String(pedido.tokens_ia || 0)], ['Versão do código', pedido.commit_codigo?.slice(0, 7)],
              ['Fim da busca', dataHora(pedido.extracao_fim)], ['Portal concluído', dataHora(pedido.concluido_em)],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3"><dt style={{ color: 'var(--color-text-secondary)' }}>{k}</dt><dd className="text-right break-all">{v}</dd></div>
            ))}
          </dl>
          {pedido.observacoes && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{pedido.observacoes}</p>}
        </Card>
      </div>

    </Pagina>
  )
}

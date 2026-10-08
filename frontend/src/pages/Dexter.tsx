import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bot, ChevronDown, Copy, ExternalLink, FileSpreadsheet, KeyRound, Loader2, RefreshCw, RotateCcw, Send, Star, XCircle } from 'lucide-react'
import { Card } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import Select from '../components/ui/Select'
import RadioGroup from '../components/ui/Radio'
import Modal from '../components/ui/Modal'
import Checkbox from '../components/ui/Checkbox'
import { ToastContainer } from '../components/ui/Toast'
import { useToast } from '../hooks/useToast'
import { useApoio } from '../hooks/useApoio'
import { useSessao } from '../lib/sessao'
import { Aviso, Esqueleto, Pagina, Vazio } from '../components/app/Pagina'
import { acionar, consultar, ErroApi } from '../lib/mitra-api'
import type { Status } from '../lib/mitra-api'
import { SF } from '../lib/sf-ids'
import { dataHora, duracao, STATUS } from '../lib/formatos'

const PROJETO = '7cf4dbde-73f3-4707-86e5-230807270374'
const ENDERECO = `https://dhsseifv2j3ti.cloudfront.net/legacy/public/serverFunction/${PROJETO}/${SF.dexter_api}/execute`
const PAGINA = 30

interface Totais { total: number; na_fila: number; andamento: number; concluidos: number; falharam: number; tempo_medio_s: number | null; concluidos_24h: number }
interface Lote { id: number; nome: string; origem: string; criado_em: string; usuario: string; total: number; na_fila: number; buscando: number; criando: number; concluidos: number; falharam: number }
interface LinhaDexter { pedido_id: string; cliente: string; site: string; status: Status; lote_id: number | null; lote: string | null; referencia: string | null; produtos: number | null; portal_url: string | null; motivo: string | null; criado_em: string; segundos: number | null; em_execucao: boolean; usuario: string; avaliacao_nota: number | null; avaliacao_problemas: string | null; avaliacao_comentario: string | null; relogio_ativo: boolean }
interface Token { id: number; prefixo: string; criado_em: string; ultimo_uso: string | null; revogado_em: string | null; executivo_id: number; usuario: string }

const n = (v: unknown) => Number(v) || 0

const PROBLEMAS: [string, string][] = [
  ['produtos_errados', 'Produtos que não são do cliente'],
  ['imagens_ruins', 'Imagens erradas ou ruins'],
  ['poucos_produtos', 'Poucos produtos'],
  ['fora_do_foco', 'Produtos fora do foco'],
  ['nomes_ruins', 'Nomes ruins ou cortados'],
  ['precos_estranhos', 'Preços estranhos'],
  ['categorias_ruins', 'Categorias ruins'],
  ['banner_ruim', 'Banner ruim'],
  ['logo_errada', 'Logo errada'],
  ['segmento_errado', 'Segmento errado'],
]

function Estrelas({ nota, onChange, tamanho = 16 }: { nota: number; onChange?: (n: number) => void; tamanho?: number }) {
  return (
    <span className="inline-flex items-center gap-1">
      {[1, 2, 3, 4, 5].map((i) => {
        const cheia = i <= nota
        const icone = <Star size={tamanho} fill={cheia ? 'var(--color-warning)' : 'none'} style={{ color: cheia ? 'var(--color-warning)' : 'var(--color-text-secondary)' }} />
        return onChange
          ? <button key={i} type="button" aria-label={`Nota ${i}`} className="cursor-pointer p-1" onClick={() => onChange(i)}>{icone}</button>
          : <span key={i}>{icone}</span>
      })}
    </span>
  )
}

function lerLinhas(texto: string) {
  return texto.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
    const [empresa = '', site = '', ...resto] = l.split(/[;\t]/).map((x) => x.trim())
    return { empresa, site, observacao: resto.join(' ').trim() }
  })
}

export default function Dexter() {
  const { executivos } = useApoio()
  const sessao = useSessao()
  const agente = !sessao.admin && sessao.cargo === 'Agente de prospecção'
  const { toasts, addToast, removeToast } = useToast()
  const [totais, setTotais] = useState<Totais | null>(null)
  const [lotes, setLotes] = useState<Lote[] | null>(null)
  const [linhas, setLinhas] = useState<LinhaDexter[] | null>(null)
  const [tokens, setTokens] = useState<Token[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [filtroStatus, setFiltroStatus] = useState('')
  const [filtroLote, setFiltroLote] = useState('')
  const [lotesAbertos, setLotesAbertos] = useState(false)
  const pedidosRef = useRef<HTMLDivElement>(null)
  const [fim, setFim] = useState(false)
  const [nomeLote, setNomeLote] = useState('')
  const [texto, setTexto] = useState('')
  const [variacoes, setVariacoes] = useState('nao')
  const [enviando, setEnviando] = useState(false)
  const [lendo, setLendo] = useState(false)
  const [planilha, setPlanilha] = useState<string | null>(null)
  const seletor = useRef<HTMLInputElement>(null)
  const [donoToken, setDonoToken] = useState('')
  const [gerando, setGerando] = useState(false)
  const [tokenNovo, setTokenNovo] = useState<{ token: string; usuario: string } | null>(null)
  const [ocupado, setOcupado] = useState<string | null>(null)
  const versao = useRef(0)
  const recebidoEm = useRef(Date.now())
  const [agora, setAgora] = useState(Date.now())
  const [avaliando, setAvaliando] = useState<LinhaDexter | null>(null)
  const [nota, setNota] = useState(0)
  const [problemas, setProblemas] = useState<Set<string>>(new Set())
  const [comentario, setComentario] = useState('')
  const [salvandoAval, setSalvandoAval] = useState(false)

  const dexter = executivos.find((e) => e.cargo === 'Agente de prospecção')
  const dono = agente ? String(sessao.executivo_id || '') : donoToken || (dexter ? String(dexter.id) : '')

  const carregarPedidos = useCallback(async (offset: number, limite = PAGINA) => {
    const v = offset === 0 ? ++versao.current : versao.current
    try {
      const r = await consultar<LinhaDexter>('dexter_pedidos', { status: filtroStatus, lote: filtroLote, limite: String(limite), offset: String(offset) })
      if (v !== versao.current) return
      if (offset === 0) recebidoEm.current = Date.now()
      setLinhas((a) => (offset === 0 ? r : [...(a || []), ...r]))
      setFim(r.length < limite)
    } catch { if (v === versao.current) setErro('Não foi possível carregar os pedidos do Dexter.') }
  }, [filtroStatus, filtroLote])

  function abrirLote(id: string) {
    setFiltroLote(id)
    if (!id) return
    setLotesAbertos(false)
    requestAnimationFrame(() => pedidosRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  const carregarResumo = useCallback(async () => {
    const [t, l] = await Promise.allSettled([
      consultar<Totais>('dexter_totais'),
      consultar<Lote>('dexter_lotes', { limite: '20', offset: '0' }),
    ])
    if (t.status === 'fulfilled') setTotais(t.value[0] || null)
    if (l.status === 'fulfilled') setLotes(l.value); else setLotes((a) => a || [])
  }, [])

  useEffect(() => {
    carregarResumo()
    consultar<Token>('dexter_tokens').then(setTokens).catch(() => setTokens([]))
  }, [carregarResumo])

  useEffect(() => { carregarPedidos(0) }, [carregarPedidos])

  const andamento = n(totais?.na_fila) + n(totais?.andamento) > 0
  const qtdLinhas = useRef(0)
  qtdLinhas.current = linhas?.length || 0
  useEffect(() => {
    if (!andamento) return
    const atualizar = () => {
      if (document.visibilityState !== 'visible') return
      carregarResumo()
      carregarPedidos(0, Math.max(PAGINA, qtdLinhas.current))
    }
    const t = setInterval(atualizar, 8000)
    document.addEventListener('visibilitychange', atualizar)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', atualizar) }
  }, [andamento, carregarResumo, carregarPedidos])

  const relogioAndando = !!linhas?.some((x) => x.relogio_ativo)
  useEffect(() => {
    if (!relogioAndando) return
    const t = setInterval(() => setAgora(Date.now()), 1000)
    return () => clearInterval(t)
  }, [relogioAndando])
  const tempoDe = (p: LinhaDexter) => (p.segundos === null || p.segundos === undefined ? null
    : Number(p.segundos) + (p.relogio_ativo ? Math.max(0, (agora - recebidoEm.current) / 1000) : 0))

  const empresas = lerLinhas(texto)

  async function lerPlanilha(arquivo: File | undefined) {
    if (!arquivo) return
    if (!/\.(xlsx|csv)$/i.test(arquivo.name)) { addToast('error', 'Envie a planilha em xlsx ou csv.'); return }
    if (arquivo.size > 2 * 1024 * 1024) { addToast('error', 'A planilha passa de 2 MB. Envie uma versão menor.'); return }
    setLendo(true)
    try {
      const conteudo = await new Promise<string>((ok, falha) => {
        const leitor = new FileReader()
        leitor.onload = () => ok(String(leitor.result).split(',')[1] || '')
        leitor.onerror = () => falha(new Error())
        leitor.readAsDataURL(arquivo)
      })
      const r = await acionar('dexter_admin', { acao: 'ler_planilha', nome_arquivo: arquivo.name, conteudo_base64: conteudo })
      const lidas = (r.empresas as { empresa: string; site: string; observacao: string }[]) || []
      if (!lidas.length) { addToast('error', 'Não achei empresas na planilha.'); return }
      setTexto(lidas.map((e) => [e.empresa, e.site, e.observacao].filter((x, i) => i < 2 || x).join('; ')).join('\n'))
      setPlanilha(arquivo.name)
      if (!nomeLote.trim()) setNomeLote(arquivo.name.replace(/\.(xlsx|csv)$/i, ''))
      addToast('success', `${lidas.length} empresas lidas da planilha. Confira e mande para a fila.`)
    } catch (e) {
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível ler a planilha.')
    } finally { setLendo(false) }
  }

  async function enviarLote(ev: React.FormEvent) {
    ev.preventDefault()
    if (!empresas.length) { addToast('error', 'Cole ao menos uma empresa: nome; site.'); return }
    const semSite = empresas.findIndex((e) => !e.empresa || !e.site)
    if (semSite >= 0) { addToast('error', `Linha ${semSite + 1}: informe nome e site.`); return }
    setEnviando(true)
    try {
      const r = await acionar('dexter_admin', { acao: 'lote', nome: nomeLote.trim(), empresas: empresas.map((e) => ({ ...e, variacoes: variacoes === 'sim' })) })
      const itens = (r.itens as unknown[]) || []
      const erros = (r.erros as unknown[]) || []
      addToast('success', `${itens.length} empresas na fila${erros.length ? ` · ${erros.length} recusadas` : ''}.`)
      setTexto(''); setNomeLote(''); setPlanilha(null)
      carregarResumo(); carregarPedidos(0)
    } catch (e) {
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível enviar o lote.')
    } finally { setEnviando(false) }
  }

  function abrirAvaliacao(p: LinhaDexter) {
    setAvaliando(p)
    setNota(n(p.avaliacao_nota))
    setProblemas(new Set((p.avaliacao_problemas || '').split(',').filter(Boolean)))
    setComentario(p.avaliacao_comentario || '')
  }

  async function salvarAvaliacao() {
    if (!avaliando || !nota) return
    const p = avaliando
    const novo = { avaliacao_nota: nota, avaliacao_problemas: [...problemas].join(','), avaliacao_comentario: comentario.trim() || null }
    setSalvandoAval(true)
    try {
      await acionar('dexter_admin', { acao: 'avaliar', pedido_id: p.pedido_id, nota, problemas: [...problemas], comentario: comentario.trim() })
      setLinhas((l) => l?.map((x) => (x.pedido_id === p.pedido_id ? { ...x, ...novo } : x)) || l)
      addToast('success', `Avaliação de ${p.cliente} salva. Os próximos portais vão levar isso em conta.`)
      setAvaliando(null)
    } catch (e) {
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível salvar a avaliação.')
    } finally { setSalvandoAval(false) }
  }

  async function mexer(p: LinhaDexter, acao: 'retentar' | 'cancelar') {
    setOcupado(p.pedido_id)
    const antes = p.status
    setLinhas((l) => l?.map((x) => (x.pedido_id === p.pedido_id ? { ...x, status: acao === 'retentar' ? 'na_fila' : 'falhou', motivo: acao === 'cancelar' ? (agente ? 'cancelado pelo Dexter' : 'cancelado pelo administrador') : null } : x)) || l)
    try {
      await acionar('dexter_admin', { acao, pedido_id: p.pedido_id })
      addToast('success', acao === 'retentar' ? `${p.cliente} voltou para a fila.` : `${p.cliente} cancelado.`)
      carregarResumo()
    } catch (e) {
      setLinhas((l) => l?.map((x) => (x.pedido_id === p.pedido_id ? { ...x, status: antes, motivo: p.motivo } : x)) || l)
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível salvar.')
    } finally { setOcupado(null) }
  }

  async function gerarToken() {
    if (!dono) { addToast('error', 'Escolha o usuário do token.'); return }
    setGerando(true)
    try {
      const r = await acionar('dexter_admin', { acao: 'gerar_token', executivo_id: dono })
      setTokenNovo({ token: String(r.token), usuario: String(r.usuario) })
      const usuario = executivos.find((e) => String(e.id) === dono)
      setTokens((l) => [{ id: Number(r.id), prefixo: String(r.prefixo), criado_em: String(r.criado_em), ultimo_uso: null, revogado_em: null, executivo_id: Number(dono), usuario: usuario?.nome || String(r.usuario || sessao.executivo || '') }, ...(l || [])])
    } catch (e) {
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível gerar o token.')
    } finally { setGerando(false) }
  }

  async function revogar(t: Token) {
    setTokens((l) => l?.map((x) => (x.id === t.id ? { ...x, revogado_em: new Date().toISOString() } : x)) || l)
    try { await acionar('dexter_admin', { acao: 'revogar_token', id: t.id }); addToast('success', `Token ${t.prefixo}… revogado.`) } catch (e) {
      setTokens((l) => l?.map((x) => (x.id === t.id ? { ...x, revogado_em: null } : x)) || l)
      addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível revogar.')
    }
  }

  function copiar(valor: string, rotulo: string) {
    navigator.clipboard.writeText(valor).then(() => addToast('success', `${rotulo} copiado.`), () => addToast('error', 'Não foi possível copiar.'))
  }

  const kpis: [string, string, string][] = totais ? [
    ['Na fila', String(n(totais.na_fila)), `${n(totais.andamento)} em andamento agora`],
    ['Portais criados', String(n(totais.concluidos)), `${n(totais.concluidos_24h)} nas últimas 24 h`],
    ['Falharam', String(n(totais.falharam)), `${Math.round(100 * n(totais.falharam) / Math.max(1, n(totais.total)))}% dos pedidos`],
    ['Tempo médio até o link', duracao(totais.tempo_medio_s), `${n(totais.total)} pedidos no total`],
  ] : []

  const exemplo = `{\n  "token": "dxt_…",\n  "lote": "Prospecção outubro",\n  "empresas": [\n    { "empresa": "Farex", "site": "farex.com.br", "referencia": "crm-123", "observacao": "", "variacoes": false }\n  ]\n}`

  return (
    <Pagina titulo="Dexter" subtitulo="Agente de prospecção: cria vários portais por vez, sem curadoria. Até 3 buscas ao mesmo tempo e um portal criado por vez."
      acao={<Button variant="secondary" className="h-10" onClick={() => { carregarResumo(); carregarPedidos(0) }}><RefreshCw size={16} /> Atualizar</Button>}>
      <ToastContainer toasts={toasts} onRemove={removeToast} />
      <Modal isOpen={!!avaliando} onClose={() => !salvandoAval && setAvaliando(null)} title={avaliando ? `Avaliar ${avaliando.cliente}` : 'Avaliar'}>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Nota do portal</span>
            <Estrelas nota={nota} onChange={setNota} tamanho={22} />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>O que deu errado</span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {PROBLEMAS.map(([chave, rotulo]) => (
                <Checkbox key={chave} id={`prob-${chave}`} label={rotulo} checked={problemas.has(chave)}
                  onChange={(v) => setProblemas((s) => { const novo = new Set(s); if (v) novo.add(chave); else novo.delete(chave); return novo })} />
              ))}
            </div>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Comentário (o que melhorar)</span>
            <textarea rows={4} value={comentario} onChange={(e) => setComentario(e.target.value)} maxLength={1000}
              placeholder="Ex.: trouxe acessórios em vez das peças; banner escuro demais"
              className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2"
              style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text)' }} />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setAvaliando(null)} disabled={salvandoAval}>Cancelar</Button>
            <Button onClick={salvarAvaliacao} disabled={!nota || salvandoAval}>{salvandoAval ? <Loader2 size={16} className="animate-spin" /> : <Star size={16} />} Salvar avaliação</Button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={!!tokenNovo} onClose={() => setTokenNovo(null)} title="Token gerado">
        {tokenNovo && (
          <div className="flex flex-col gap-3">
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Token de {tokenNovo.usuario}. Copie agora: ele não aparece de novo. Os pedidos feitos com ele ficam no nome de {tokenNovo.usuario}.</p>
            <code className="block break-all rounded-md p-3 text-sm" style={{ backgroundColor: 'var(--color-nav-hover)', color: 'var(--color-text)' }}>{tokenNovo.token}</code>
            <div className="flex justify-end"><Button onClick={() => copiar(tokenNovo.token, 'Token')}><Copy size={16} /> Copiar token</Button></div>
          </div>
        )}
      </Modal>
      {erro && <Aviso tipo="danger" titulo={erro} />}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {totais === null ? Array.from({ length: 4 }).map((_, i) => <Card key={i}><Esqueleto linhas={2} /></Card>) : kpis.map(([titulo, valor, detalhe]) => (
          <Card key={titulo} className="p-5 flex flex-col gap-1">
            <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{titulo}</span>
            <span className="text-2xl font-semibold tabular-nums">{valor}</span>
            <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{detalhe}</span>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card className="p-5">
          <form onSubmit={enviarLote} className="flex flex-col gap-3">
            <h2 className="text-base font-semibold">Novo lote</h2>
            <Input label="Nome do lote (opcional)" placeholder="Ex.: Prospecção outubro" value={nomeLote} onChange={(e) => setNomeLote(e.target.value)} />
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Planilha de empresas</span>
              <input ref={seletor} type="file" accept=".xlsx,.csv" className="hidden"
                onChange={(e) => { lerPlanilha(e.target.files?.[0]); e.target.value = '' }} />
              <button type="button" disabled={lendo || enviando} onClick={() => seletor.current?.click()}
                className="flex items-center gap-2 h-10 px-3 rounded-md text-sm cursor-pointer disabled:cursor-default"
                style={{ border: '1px dashed var(--color-border)', color: planilha ? 'var(--color-primary-text)' : 'var(--color-text-secondary)', backgroundColor: planilha ? 'var(--color-primary-bg)' : 'transparent' }}>
                {lendo ? <Loader2 size={16} className="animate-spin" /> : <FileSpreadsheet size={16} />}
                {lendo ? 'Lendo a planilha…' : planilha ? `${planilha} · escolher outra` : 'Anexar planilha (xlsx ou csv)'}
              </button>
              <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Colunas: empresa (ou cliente), site e, se quiser, observação. A lista abaixo é preenchida para você conferir.</span>
            </div>
            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Empresas: uma por linha, no formato nome; site; observação</span>
              <textarea rows={6} value={texto} onChange={(e) => setTexto(e.target.value)} disabled={enviando}
                placeholder={'Farex; farex.com.br\nKRW; krw.com.br; foco nas peças'}
                className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2"
                style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text)' }} />
            </label>
            <RadioGroup label="Criar variações" direction="horizontal" value={variacoes} onChange={setVariacoes} disabled={enviando}
              options={[{ value: 'nao', label: 'Não' }, { value: 'sim', label: 'Sim' }]} />
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{empresas.length} {empresas.length === 1 ? 'empresa' : 'empresas'} · máximo 50</span>
              <Button type="submit" className="ml-auto h-10" disabled={enviando || !empresas.length}>
                {enviando ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />} {enviando ? 'Enviando…' : 'Mandar para a fila'}
              </Button>
            </div>
          </form>
        </Card>

        <Card className="p-5 flex flex-col gap-3">
          <h2 className="text-base font-semibold">API</h2>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>POST com JSON. O token vai no corpo e define em nome de quem os portais são criados. Reenviar a mesma referência não cria outro portal. Para consultar, mande o token com <code>pedido_id</code>, <code>referencia_consulta</code> ou <code>lote_id</code>.</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate rounded-md px-3 py-2 text-sm" style={{ backgroundColor: 'var(--color-nav-hover)' }} title={ENDERECO}>{ENDERECO}</code>
            <Button variant="secondary" className="h-10" onClick={() => copiar(ENDERECO, 'Endereço')}><Copy size={16} /></Button>
          </div>
          <pre className="rounded-md p-3 text-sm overflow-x-auto" style={{ backgroundColor: 'var(--color-nav-hover)' }}>{exemplo}</pre>
          <div className="flex flex-wrap items-end gap-3">
            {!agente && <div className="w-full sm:w-64">
              <Select label="Usuário do token" value={dono} onChange={setDonoToken}
                options={executivos.filter((e) => e.ativo).map((e) => ({ value: String(e.id), label: e.cargo ? `${e.nome} · ${e.cargo}` : e.nome }))} />
            </div>}
            <Button className="h-10" onClick={gerarToken} disabled={gerando}>{gerando ? <Loader2 size={16} className="animate-spin" /> : <KeyRound size={16} />} Gerar token</Button>
          </div>
          {tokens === null ? <Esqueleto linhas={2} /> : tokens.length > 0 && (
            <div className="overflow-x-auto"><table className="w-full"><thead><tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
              <th className="px-3 py-3 font-medium">Token</th><th className="px-3 py-3 font-medium">Usuário</th><th className="px-3 py-3 font-medium">Último uso</th><th className="px-3 py-3" /></tr></thead>
              <tbody>{tokens.map((t) => (
                <tr key={t.id} style={{ borderTop: '1px solid var(--color-border)' }}>
                  <td className="px-3 py-3"><div className="leading-tight"><div className="font-medium">{t.prefixo}…</div><div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>criado {dataHora(t.criado_em)}</div></div></td>
                  <td className="px-3 py-3">{t.usuario}</td>
                  <td className="px-3 py-3 tabular-nums">{t.ultimo_uso ? dataHora(t.ultimo_uso) : 'nunca'}</td>
                  <td className="px-3 py-3 text-right">{t.revogado_em ? <Badge variant="neutral">Revogado</Badge> : (
                    <Button variant="ghost" size="sm" onClick={() => revogar(t)}>Revogar</Button>
                  )}</td>
                </tr>))}</tbody></table></div>
          )}
        </Card>
      </div>

      <Card className="p-5 flex flex-col gap-3">
        <button type="button" className="flex items-center gap-2 cursor-pointer text-left" aria-expanded={lotesAbertos} onClick={() => setLotesAbertos((a) => !a)}>
          <h2 className="text-base font-semibold mr-auto">Lotes</h2>
          {lotes && lotes.length > 0 && <Badge variant="neutral">{lotes.length}</Badge>}
          {filtroLote && lotes && <span className="text-sm truncate" style={{ color: 'var(--color-primary-text)' }}>{lotes.find((l) => String(l.id) === filtroLote)?.nome}</span>}
          <ChevronDown size={16} className="ml-auto shrink-0 transition-transform" style={{ transform: lotesAbertos ? 'rotate(180deg)' : undefined, color: 'var(--color-text-secondary)' }} />
        </button>
        {!lotesAbertos ? null : lotes === null ? <Esqueleto linhas={3} /> : lotes.length === 0 ? (
          <Vazio titulo="Nenhum lote ainda" texto="Cole uma lista de empresas em Novo lote ou chame a API com um token." />
        ) : (
          <div className="overflow-x-auto"><table className="w-full"><thead><tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
            <th className="px-3 py-3 font-medium">Lote</th><th className="px-3 py-3 font-medium">Progresso</th><th className="px-3 py-3 font-medium text-right">Prontos</th><th className="px-3 py-3 font-medium text-right">Falharam</th><th className="px-3 py-3 font-medium text-right">Na fila</th></tr></thead>
            <tbody>{lotes.map((l) => {
              const feitos = n(l.concluidos) + n(l.falharam)
              const pct = Math.round(100 * feitos / Math.max(1, n(l.total)))
              const ativo = filtroLote === String(l.id)
              return (
                <tr key={l.id} className="cursor-pointer transition-colors hover:bg-[var(--color-nav-hover)]" style={{ borderTop: '1px solid var(--color-border)', backgroundColor: ativo ? 'var(--color-primary-bg)' : undefined }}
                  onClick={() => abrirLote(ativo ? '' : String(l.id))}>
                  <td className="px-3 py-3"><div className="leading-tight"><div className="font-medium">{l.nome}</div><div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{l.usuario} · {l.origem === 'tela' ? 'pela tela' : 'pela API'} · {dataHora(l.criado_em)}</div></div></td>
                  <td className="px-3 py-3 w-48">
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 rounded-full overflow-hidden" style={{ backgroundColor: 'var(--color-border)' }}><div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: 'var(--color-primary)' }} /></div>
                      <span className="text-meta tabular-nums">{feitos}/{n(l.total)}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums">{n(l.concluidos)}</td>
                  <td className="px-3 py-3 text-right tabular-nums" style={{ color: n(l.falharam) ? 'var(--color-danger)' : undefined }}>{n(l.falharam)}</td>
                  <td className="px-3 py-3 text-right tabular-nums">{n(l.na_fila) + n(l.buscando) + n(l.criando)}</td>
                </tr>)
            })}</tbody></table></div>
        )}
      </Card>

      <div ref={pedidosRef} className="scroll-mt-4"><Card className="p-5 flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <h2 className="text-base font-semibold mr-auto">Pedidos do Dexter</h2>
          <div className="w-full sm:w-44">
            <Select label="Situação" value={filtroStatus} onChange={setFiltroStatus}
              options={[{ value: '', label: 'Todas' }, { value: 'na_fila', label: 'Na fila' }, { value: 'extraindo', label: 'Buscando' }, { value: 'criando', label: 'Criando portal' }, { value: 'concluido', label: 'Concluído' }, { value: 'falhou', label: 'Falhou' }]} />
          </div>
          {filtroLote && <Button variant="secondary" className="h-10" onClick={() => setFiltroLote('')}><XCircle size={16} /> Tirar filtro do lote</Button>}
        </div>
        {linhas === null ? <Esqueleto linhas={5} /> : linhas.length === 0 ? (
          <Vazio titulo="Nenhum pedido" texto={filtroStatus || filtroLote ? 'Nada com esses filtros.' : 'Os portais pedidos ao Dexter aparecem aqui.'} />
        ) : (
          <div className="overflow-x-auto"><table className="w-full"><thead><tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
            <th className="px-3 py-3 font-medium">Empresa</th><th className="px-3 py-3 font-medium">Situação</th><th className="px-3 py-3 font-medium text-right">Produtos</th><th className="px-3 py-3 font-medium text-right">Tempo</th><th className="px-3 py-3 font-medium">Portal</th><th className="px-3 py-3 font-medium">Avaliação</th><th className="px-3 py-3" /></tr></thead>
            <tbody>{linhas.map((p) => {
              const falhou = p.status === 'falhou' || p.status === 'precisa_catalogo'
              const st = STATUS[p.status] || { rotulo: p.status, variante: 'neutral' as const }
              return (
                <tr key={p.pedido_id} style={{ borderTop: '1px solid var(--color-border)' }}>
                  <td className="px-3 py-3"><div className="leading-tight">
                    <Link to={`/pedidos/${p.pedido_id}`} className="font-medium cursor-pointer">{p.cliente}</Link>
                    <div className="text-sm truncate max-w-xs" style={{ color: 'var(--color-text-secondary)' }}>
                      {p.site && <a href={/^https?:\/\//i.test(p.site) ? p.site : `https://${p.site}`} target="_blank" rel="noopener noreferrer" className="cursor-pointer hover:underline" style={{ color: 'var(--color-primary-text)' }}>{p.site.replace(/^https?:\/\//, '').replace(/\/$/, '')}</a>}
                      {(p.referencia || p.lote) && ` · ${[p.referencia, p.lote].filter(Boolean).join(' · ')}`}
                    </div>
                  </div></td>
                  <td className="px-3 py-3"><div className="leading-tight">
                    <Badge variant={st.variante} dot={p.em_execucao}>{st.rotulo}</Badge>
                    {falhou && p.motivo && <div className="text-sm mt-1 max-w-xs line-clamp-2" style={{ color: 'var(--color-text-secondary)' }} title={p.motivo}>{p.motivo}</div>}
                  </div></td>
                  <td className="px-3 py-3 text-right tabular-nums">{p.produtos ?? '—'}</td>
                  <td className="px-3 py-3 text-right tabular-nums whitespace-nowrap">{duracao(tempoDe(p))}</td>
                  <td className="px-3 py-3">{p.portal_url ? <a href={p.portal_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm cursor-pointer" style={{ color: 'var(--color-primary-text)' }}>Abrir <ExternalLink size={14} /></a> : '—'}</td>
                  <td className="px-3 py-3 whitespace-nowrap">
                    {p.status === 'concluido' || falhou ? (
                      <button type="button" className="cursor-pointer leading-tight text-left" onClick={() => abrirAvaliacao(p)} title={p.avaliacao_comentario || undefined}>
                        {p.avaliacao_nota ? <Estrelas nota={n(p.avaliacao_nota)} tamanho={14} /> : <span className="text-sm" style={{ color: 'var(--color-primary-text)' }}>Avaliar</span>}
                        {p.avaliacao_problemas && <div className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>{p.avaliacao_problemas.split(',').filter(Boolean).length} problema(s)</div>}
                      </button>
                    ) : '—'}
                  </td>
                  <td className="px-3 py-3 text-right whitespace-nowrap">
                    {falhou && <Button variant="ghost" size="sm" disabled={ocupado === p.pedido_id} onClick={() => mexer(p, 'retentar')}><RotateCcw size={14} /> Tentar de novo</Button>}
                    {p.status === 'na_fila' && <Button variant="ghost" size="sm" disabled={ocupado === p.pedido_id} onClick={() => mexer(p, 'cancelar')}><XCircle size={14} /> Cancelar</Button>}
                  </td>
                </tr>)
            })}</tbody></table>
            {!fim && <div className="flex justify-center pt-3"><Button variant="secondary" onClick={() => carregarPedidos(linhas.length)}><Bot size={16} /> Carregar mais</Button></div>}
          </div>
        )}
      </Card></div>
    </Pagina>
  )
}

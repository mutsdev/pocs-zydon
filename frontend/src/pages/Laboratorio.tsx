import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, ExternalLink, FlaskConical, Loader2, Maximize2, Sparkles, Star } from 'lucide-react'
import { Card } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Select from '../components/ui/Select'
import Modal from '../components/ui/Modal'
import { ToastContainer } from '../components/ui/Toast'
import { useToast } from '../hooks/useToast'
import { Aviso, Esqueleto, Pagina, Vazio } from '../components/app/Pagina'
import { acionar, consultar, ErroApi } from '../lib/mitra-api'

interface Rodada { id: number; numero: number; situacao: string; banners: number; prontos: number; gerando: number; falharam: number; avaliacoes: number; media: number | null }
interface ItemLab {
  id: number; rodada: number; pedido_id: string; cliente: string; site: string | null; portal_url: string | null
  modelo: string; situacao: string; erro: string | null; media: number | null; avaliacoes: number
  minha_nota: number | null; minhas_marcas: string | null; meu_comentario: string | null
  login_base64: string | null; cabecalho_base64: string | null
}

const PAGINA = 10
const MARCAS: [string, string][] = [
  ['logo', 'Logo'], ['cores', 'Cores'], ['produto', 'Produto'],
  ['composicao', 'Composição'], ['texto', 'Texto'], ['amador', 'Parece amador'],
]
const MODELO: Record<string, string> = { do_zero_livre: 'Do zero livre (IA)', do_zero: 'Do zero (IA)', destaque: 'Destaque', trio: 'Trio', padrao: 'Padrão gráfico', so_marca: 'Só a marca', diagonal: 'Diagonal', vitrine: 'Vitrine', em_uso: 'Produto em uso', padrao_marca: 'Linhas da marca' }
const SITUACAO: Record<string, { rotulo: string; variante: 'success' | 'danger' | 'info' | 'warning' | 'neutral' }> = {
  na_fila: { rotulo: 'Na fila', variante: 'neutral' },
  gerando: { rotulo: 'Gerando', variante: 'info' },
  pronto: { rotulo: 'Pronto', variante: 'warning' },
  aplicando: { rotulo: 'Aplicando', variante: 'info' },
  aplicado: { rotulo: 'No portal', variante: 'success' },
  falhou: { rotulo: 'Falhou', variante: 'danger' },
}
const num = (v: unknown) => Number(v || 0)
const media = (v: number | null) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 1 }))

function Estrelas({ nota, onChange }: { nota: number; onChange: (n: number) => void }) {
  return (
    <span className="inline-flex items-center">
      {[1, 2, 3, 4, 5].map((i) => (
        <button key={i} type="button" aria-label={`Nota ${i}`} className="cursor-pointer p-1" onClick={() => onChange(i)}>
          <Star size={20} fill={i <= nota ? 'var(--color-warning)' : 'none'} style={{ color: i <= nota ? 'var(--color-warning)' : 'var(--color-text-secondary)' }} />
        </button>
      ))}
    </span>
  )
}

function Avaliacao({ item, aoSalvar, aoAprovar }: { item: ItemLab; aoSalvar: (i: ItemLab, nota: number, marcas: string[], comentario: string) => Promise<void>; aoAprovar: (i: ItemLab) => void }) {
  const [nota, setNota] = useState(item.minha_nota || 0)
  const [marcas, setMarcas] = useState<Set<string>>(new Set((item.minhas_marcas || '').split(',').filter(Boolean)))
  const [comentario, setComentario] = useState(item.meu_comentario || '')
  const [salvando, setSalvando] = useState(false)
  const alterado = nota !== (item.minha_nota || 0) || comentario !== (item.meu_comentario || '')
    || [...marcas].sort().join(',') !== (item.minhas_marcas || '').split(',').filter(Boolean).sort().join(',')
  const alternar = (m: string) => setMarcas((a) => { const n = new Set(a); if (n.has(m)) n.delete(m); else n.add(m); return n })
  const salvar = async () => { setSalvando(true); try { await aoSalvar(item, nota, [...marcas], comentario) } finally { setSalvando(false) } }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Estrelas nota={nota} onChange={setNota} />
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Média {media(item.media)} · {item.avaliacoes} {item.avaliacoes === 1 ? 'avaliação' : 'avaliações'}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>O que precisa melhorar</span>
        <div className="flex flex-wrap gap-2">
          {MARCAS.map(([chave, rotulo]) => {
            const ativa = marcas.has(chave)
            return (
              <button key={chave} type="button" onClick={() => alternar(chave)} aria-pressed={ativa}
                className="h-9 px-3 rounded-full text-sm cursor-pointer border transition-colors"
                style={{ backgroundColor: ativa ? 'var(--color-danger-bg)' : 'transparent', color: ativa ? 'var(--color-danger)' : 'var(--color-text)', borderColor: ativa ? 'var(--color-danger-border)' : 'var(--color-border)' }}>
                {rotulo}
              </button>
            )
          })}
        </div>
      </div>
      <textarea rows={2} maxLength={1000} value={comentario} onChange={(e) => setComentario(e.target.value)}
        placeholder="Comentário: o que você mudaria neste banner?"
        className="w-full px-3 py-2 text-sm rounded-md border focus:outline-none"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }} />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={salvar} disabled={!nota || salvando || !alterado}>
          {salvando && <Loader2 size={16} className="animate-spin" />}
          {item.minha_nota ? 'Atualizar avaliação' : 'Salvar avaliação'}
        </Button>
        {item.situacao === 'pronto' && (
          <Button size="sm" variant="secondary" onClick={() => aoAprovar(item)}>
            <CheckCircle2 size={16} /> Aprovar e aplicar no portal
          </Button>
        )}
      </div>
    </div>
  )
}

export default function Laboratorio() {
  const { toasts, addToast, removeToast } = useToast()
  const [rodadas, setRodadas] = useState<Rodada[] | null>(null)
  const [itens, setItens] = useState<ItemLab[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [rodada, setRodada] = useState('')
  const [filtro, setFiltro] = useState('')
  const [fim, setFim] = useState(false)
  const [abrindo, setAbrindo] = useState(false)
  const [ampliada, setAmpliada] = useState<{ titulo: string; src: string } | null>(null)
  const [aprovando, setAprovando] = useState<ItemLab | null>(null)
  const [confirmando, setConfirmando] = useState(false)
  const versao = useRef(0)

  const carregarRodadas = useCallback(async () => {
    try { setRodadas(await consultar<Rodada>('banner_lab_rodadas')) } catch { setRodadas((a) => a || []) }
  }, [])

  const carregarItens = useCallback(async (offset: number) => {
    const v = offset === 0 ? ++versao.current : versao.current
    try {
      const r = await consultar<ItemLab>('banner_lab_listar', { rodada, filtro, limite: String(PAGINA), offset: String(offset) })
      if (v !== versao.current) return
      setItens((a) => (offset === 0 ? r : [...(a || []), ...r]))
      setFim(r.length < PAGINA)
      setErro(null)
    } catch { if (v === versao.current) setErro('Não foi possível carregar os banners do laboratório.') }
  }, [rodada, filtro])

  useEffect(() => { carregarRodadas() }, [carregarRodadas])
  useEffect(() => { carregarItens(0) }, [carregarItens])

  const atual = rodadas?.[0]
  const gerandoAgora = num(atual?.gerando) > 0

  const novaRodada = async () => {
    setAbrindo(true)
    try {
      const r = await acionar('banner_lab_acao', { acao: 'nova_rodada' })
      addToast('success', `Rodada ${r.rodada} aberta: ${r.banners} banners entrando na fila.`)
      setRodada('')
      await Promise.allSettled([carregarRodadas(), carregarItens(0)])
    } catch (e) { addToast('error', e instanceof ErroApi ? String(e.detalhe.mensagem || e.message) : 'Não foi possível abrir a rodada.') }
    finally { setAbrindo(false) }
  }

  const salvar = async (item: ItemLab, nota: number, marcas: string[], comentario: string) => {
    const antes = item
    const depois = { ...item, minha_nota: nota, minhas_marcas: marcas.join(','), meu_comentario: comentario || null,
      avaliacoes: item.minha_nota ? item.avaliacoes : item.avaliacoes + 1 }
    setItens((a) => (a || []).map((x) => (x.id === item.id ? depois : x)))
    try {
      await acionar('banner_lab_acao', { acao: 'avaliar', lab_id: item.id, nota, marcas, comentario })
      addToast('success', 'Avaliação salva.')
      carregarRodadas()
    } catch (e) {
      setItens((a) => (a || []).map((x) => (x.id === item.id ? antes : x)))
      addToast('error', e instanceof ErroApi && e.codigo === 'EXECUTIVO_NAO_CADASTRADO' ? 'Seu usuário precisa estar cadastrado para avaliar.' : 'Não foi possível salvar a avaliação.')
    }
  }

  const aprovar = async () => {
    if (!aprovando) return
    setConfirmando(true)
    try {
      await acionar('banner_lab_acao', { acao: 'aprovar', lab_id: aprovando.id })
      setItens((a) => (a || []).map((x) => (x.id === aprovando.id ? { ...x, situacao: 'aplicando' } : x)))
      addToast('success', 'Banner aprovado: aplicando no portal.')
      setAprovando(null)
    } catch (e) { addToast('error', e instanceof ErroApi ? e.message : 'Não foi possível aprovar o banner.') }
    finally { setConfirmando(false) }
  }

  const opcoesRodada = [{ value: '', label: 'Todas as rodadas' }, ...(rodadas || []).map((r) => ({ value: String(r.numero), label: `Rodada ${r.numero}` }))]

  return (
    <Pagina titulo="Laboratório de banners" subtitulo="Banners novos de 5 em 5. Dê nota e comente: a próxima rodada sai com as correções."
      acao={<Button onClick={novaRodada} disabled={abrindo || gerandoAgora}>
        {abrindo ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
        {gerandoAgora ? 'Rodada em geração' : 'Gerar próximos 5'}
      </Button>}>
      <ToastContainer toasts={toasts} onRemove={removeToast} />

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {[
          ['Rodada atual', atual ? String(atual.numero) : '—'],
          ['Prontos para avaliar', atual ? `${num(atual.prontos)} de ${num(atual.banners)}` : '—'],
          ['Gerando', atual ? String(num(atual.gerando)) : '—'],
          ['Média da rodada', atual ? media(atual.media) : '—'],
        ].map(([rotulo, valor]) => (
          <Card key={rotulo} className="p-5 flex flex-col gap-1">
            <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{rotulo}</span>
            <span className="text-2xl font-semibold tabular-nums" style={{ color: 'var(--color-text)' }}>{valor}</span>
          </Card>
        ))}
      </div>

      {rodadas && rodadas.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {rodadas.slice(0, 6).map((r) => (
            <Badge key={r.id} variant={r.numero === atual?.numero ? 'info' : 'neutral'}>Rodada {r.numero}: média {media(r.media)}</Badge>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-44"><Select label="Rodada" options={opcoesRodada} value={rodada} onChange={setRodada} /></div>
        <div className="w-44"><Select label="Mostrar" value={filtro} onChange={setFiltro}
          options={[{ value: '', label: 'Todos' }, { value: 'pendentes', label: 'Falta eu avaliar' }, { value: 'avaliados', label: 'Já avaliei' }]} /></div>
      </div>

      {erro && <Aviso tipo="danger" titulo={erro}>Tente recarregar a página.</Aviso>}
      {!itens && !erro && <Card><Esqueleto linhas={6} /></Card>}
      {itens && itens.length === 0 && (
        <Card><Vazio titulo="Nenhum banner aqui ainda" texto="Gere a primeira rodada: pego 5 portais já criados e faço banners novos para vocês avaliarem."
          acao={<Button onClick={novaRodada} disabled={abrindo || gerandoAgora}><FlaskConical size={16} /> Gerar próximos 5</Button>} /></Card>
      )}

      <div className="flex flex-col gap-6">
        {(itens || []).map((item) => {
          const s = SITUACAO[item.situacao] || { rotulo: item.situacao, variante: 'neutral' as const }
          const login = item.login_base64 ? `data:image/jpeg;base64,${item.login_base64}` : null
          const cabecalho = item.cabecalho_base64 ? `data:image/jpeg;base64,${item.cabecalho_base64}` : null
          return (
            <Card key={item.id} className="p-5 flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>{item.cliente}</span>
                <Badge variant={s.variante} dot>{s.rotulo}</Badge>
                <Badge variant="neutral">{MODELO[item.modelo] || item.modelo}</Badge>
                <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Rodada {item.rodada}</span>
                {item.portal_url && (
                  <a href={item.portal_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-2 text-sm cursor-pointer" style={{ color: 'var(--color-primary-text)' }}>
                    Abrir portal <ExternalLink size={14} />
                  </a>
                )}
              </div>
              {item.situacao === 'falhou' && <Aviso tipo="danger" titulo="Este banner não saiu">{item.erro || 'Erro sem detalhe.'}</Aviso>}
              {['na_fila', 'gerando'].includes(item.situacao) && (
                <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  <Loader2 size={16} className="animate-spin" /> {item.situacao === 'gerando' ? 'Montando o banner…' : 'Esperando a vez na fila.'}
                </div>
              )}
              {(login || cabecalho) && (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                  {cabecalho && (
                    <button type="button" className="lg:col-span-2 relative group cursor-pointer text-left" onClick={() => setAmpliada({ titulo: `${item.cliente}: cabeçalho`, src: cabecalho })}>
                      <span className="text-sm block mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>Cabeçalho</span>
                      <img src={cabecalho} alt={`Banner de cabeçalho de ${item.cliente}`} className="w-full rounded-md" loading="lazy" />
                      <Maximize2 size={16} className="absolute right-2 bottom-2 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--color-on-primary)' }} />
                    </button>
                  )}
                  {login && (
                    <button type="button" className="relative group cursor-pointer text-left" onClick={() => setAmpliada({ titulo: `${item.cliente}: tela de login`, src: login })}>
                      <span className="text-sm block mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>Tela de login</span>
                      <img src={login} alt={`Banner da tela de login de ${item.cliente}`} className="w-full rounded-md" loading="lazy" />
                    </button>
                  )}
                </div>
              )}
              {['pronto', 'aplicando', 'aplicado'].includes(item.situacao) && <Avaliacao item={item} aoSalvar={salvar} aoAprovar={setAprovando} />}
            </Card>
          )
        })}
      </div>

      {itens && itens.length > 0 && !fim && (
        <div className="flex justify-center"><Button variant="secondary" onClick={() => carregarItens(itens.length)}>Carregar mais</Button></div>
      )}

      <Modal isOpen={!!ampliada} onClose={() => setAmpliada(null)} title={ampliada?.titulo || ''} size="lg">
        {ampliada && <img src={ampliada.src} alt={ampliada.titulo} className="w-full rounded-md" />}
      </Modal>
      <Modal isOpen={!!aprovando} onClose={() => !confirmando && setAprovando(null)} title="Aplicar no portal?">
        <div className="flex flex-col gap-3">
          <p className="text-sm" style={{ color: 'var(--color-text)' }}>
            O banner de {aprovando?.cliente} substitui o cabeçalho e a tela de login do portal no ar. O banner atual sai.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setAprovando(null)} disabled={confirmando}>Cancelar</Button>
            <Button onClick={aprovar} disabled={confirmando}>{confirmando && <Loader2 size={16} className="animate-spin" />} Aplicar</Button>
          </div>
        </div>
      </Modal>
    </Pagina>
  )
}

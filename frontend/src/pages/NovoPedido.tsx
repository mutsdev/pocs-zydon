import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Globe, Loader2 } from 'lucide-react'
import { Card } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import RadioGroup from '../components/ui/Radio'
import Select from '../components/ui/Select'
import { useApoio } from '../hooks/useApoio'
import CampoAnexo from '../components/app/CampoAnexo'
import { Pagina } from '../components/app/Pagina'
import { acionar, ErroApi } from '../lib/mitra-api'
import { enviarAnexo, validarArquivo } from '../lib/anexo'
import { useSessao } from '../lib/sessao'

export default function NovoPedido() {
  const sessao = useSessao()
  const navegar = useNavigate()
  const { executivos } = useApoio()
  const [dono, setDono] = useState('')
  const opcoesDono = executivos
    .filter((e) => e.ativo)
    .map((e) => ({ value: e.id === sessao.executivo_id ? '' : String(e.id), label: e.id === sessao.executivo_id ? `${e.nome} · teste` : e.cargo ? `${e.nome} · ${e.cargo}` : e.nome }))
    .sort((a, b) => (a.value === '' ? -1 : b.value === '' ? 1 : 0))
  const [cliente, setCliente] = useState('')
  const [site, setSite] = useState('')
  const [observacao, setObservacao] = useState('')
  const [variacoes, setVariacoes] = useState('nao')
  const [arquivo, setArquivo] = useState<File | null>(null)
  const [progresso, setProgresso] = useState<number | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  async function enviar(ev: React.FormEvent) {
    ev.preventDefault()
    setErro(null)
    if (!cliente.trim() || (!site.trim() && !arquivo)) {
      setErro('Informe o cliente e o site, ou anexe o catálogo quando o cliente não tiver site.')
      return
    }
    const problema = arquivo ? validarArquivo(arquivo) : null
    if (problema) { setErro(problema); return }
    setEnviando(true)
    let pedidoId = ''
    try {
      const r = await acionar('pedido_abrir', { ...(sessao.admin && dono ? { executivo: dono } : {}), cliente: cliente.trim(), site: site.trim(), observacao: observacao.trim(), variacoes: variacoes === 'sim', anexo_nome: arquivo?.name || '' })
      pedidoId = String(r.pedido_id)
      if (arquivo) {
        setProgresso(0)
        await enviarAnexo(pedidoId, arquivo, setProgresso)
      }
      navegar(`/pedidos/${pedidoId}`)
    } catch (e) {
      const texto = e instanceof ErroApi ? e.message : 'Não foi possível abrir o pedido. Tente de novo.'
      if (pedidoId) navegar(`/pedidos/${pedidoId}`, { state: { aviso: `O pedido foi aberto, mas o anexo não chegou: ${texto}` } })
      else setErro(texto)
    } finally {
      setEnviando(false)
      setProgresso(null)
    }
  }

  return (
    <Pagina titulo="Novo pedido de POC" subtitulo="Informe o cliente e o site. O sistema identifica o segmento, busca os produtos, gera os banners e leva você pela curadoria até o link do portal.">
      <Card className="p-5 max-w-2xl">
        <form onSubmit={enviar} className="flex flex-col gap-4">
          {sessao.admin ? (
            <div className="flex flex-col gap-1.5">
              <Select label="Para qual usuário é o portal (opcional)" placeholder="Vazio = fica com você, para testes" value={dono} onChange={setDono}
                options={opcoesDono} disabled={enviando} />
              <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Se escolher alguém, o pedido fica com esse usuário, que passa a vê-lo na lista dele. Vazio, fica com você.</span>
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Usuário</span>
              <span className="text-sm" style={{ color: 'var(--color-text)' }}>{sessao.executivo} · {sessao.cargo || 'Executivo comercial'} · {sessao.email}</span>
            </div>
          )}
          <Input label="Cliente" placeholder="Ex.: Distribuidora JH" value={cliente} onChange={(e) => setCliente(e.target.value)} />
          <Input label="Site do cliente" placeholder={arquivo ? 'Opcional com anexo' : 'www.cliente.com.br'} value={site} onChange={(e) => setSite(e.target.value)} />
          <RadioGroup label="Criar variações" direction="horizontal" value={variacoes} onChange={setVariacoes} disabled={enviando}
            options={[{ value: 'nao', label: 'Não' }, { value: 'sim', label: 'Sim' }]} />
          <CampoAnexo arquivo={arquivo} onChange={setArquivo} desativado={enviando}
            ajuda="Sem site, ou com um site sem produtos? Anexe o catálogo: o sistema lê nome, preço e foto de cada produto." />
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Observação (opcional)</span>
            <textarea rows={3} maxLength={500} value={observacao} onChange={(e) => setObservacao(e.target.value)} disabled={enviando}
              placeholder="Ex.: só produtos femininos. Variação de tamanho. Foco nas peças, não na bicicleta."
              className="w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2"
              style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text)' }} />
          </label>
          {erro && <p className="text-sm" style={{ color: 'var(--color-danger)' }}>{erro}</p>}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={enviando} className="h-10">
              {enviando ? <Loader2 size={16} className="animate-spin" /> : <Globe size={16} />}
              {progresso !== null ? `Enviando o arquivo… ${Math.round(progresso * 100)}%` : enviando ? 'Abrindo pedido…' : arquivo ? 'Ler o catálogo' : 'Buscar produtos'}
            </Button>
          </div>
        </form>
      </Card>
    </Pagina>
  )
}

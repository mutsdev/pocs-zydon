import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Globe, Loader2 } from 'lucide-react'
import { Card } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import Select from '../components/ui/Select'
import { Aviso, Pagina } from '../components/app/Pagina'
import { useApoio } from '../hooks/useApoio'
import { acionar, ErroApi } from '../lib/mitra-api'

export default function NovoPedido() {
  const { executivos, segmentos, erro: erroApoio } = useApoio()
  const navegar = useNavigate()
  const [executivo, setExecutivo] = useState(() => localStorage.getItem('poc_executivo') || '')
  const [cliente, setCliente] = useState('')
  const [site, setSite] = useState('')
  const [segmento, setSegmento] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const ativos = executivos.filter((e) => e.ativo)

  async function enviar(ev: React.FormEvent) {
    ev.preventDefault()
    setErro(null)
    if (!executivo || !cliente.trim() || !site.trim()) {
      setErro('Escolha o seu nome e informe o cliente e o site.')
      return
    }
    setEnviando(true)
    try {
      localStorage.setItem('poc_executivo', executivo)
      const r = await acionar('pedido_abrir', { executivo, cliente: cliente.trim(), site: site.trim(), segmento })
      navegar(`/pedidos/${r.pedido_id}`)
    } catch (e) {
      setErro(e instanceof ErroApi ? e.message : 'Não foi possível abrir o pedido. Tente de novo.')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Pagina titulo="Novo pedido de POC" subtitulo="Informe o cliente e o site. O sistema busca os produtos, gera os banners e leva você pela curadoria até o link do portal.">
      {erroApoio && <Aviso tipo="danger" titulo={erroApoio} />}
      <Card className="p-5 max-w-2xl">
        <form onSubmit={enviar} className="flex flex-col gap-4">
          <Select label="Seu nome" placeholder="Escolha na lista" value={executivo} onChange={setExecutivo}
            options={ativos.map((e) => ({ value: String(e.id), label: e.nome }))} />
          {executivos.length > 0 && ativos.length === 0 && (
            <Aviso titulo="Nenhum executivo ativo">Peça ao administrador para cadastrar o seu nome em Executivos.</Aviso>
          )}
          {executivos.length === 0 && !erroApoio && (
            <Aviso tipo="info" titulo="A lista de executivos está vazia">Cadastre os nomes em Executivos antes do primeiro pedido.</Aviso>
          )}
          <Input label="Cliente" placeholder="Ex.: Distribuidora JH" value={cliente} onChange={(e) => setCliente(e.target.value)} />
          <Input label="Site do cliente" placeholder="www.cliente.com.br" value={site} onChange={(e) => setSite(e.target.value)} />
          <Select label="Segmento (opcional)" value={segmento} onChange={setSegmento}
            options={[{ value: '', label: 'Deixar o sistema identificar' }, ...segmentos.map((s) => ({ value: s, label: s }))]} />
          {erro && <p className="text-sm" style={{ color: 'var(--color-danger)' }}>{erro}</p>}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={enviando} className="h-10">
              {enviando ? <Loader2 size={16} className="animate-spin" /> : <Globe size={16} />}
              {enviando ? 'Abrindo pedido…' : 'Buscar produtos'}
            </Button>
            <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>A busca leva de 10 s a 1 min.</span>
          </div>
        </form>
      </Card>
    </Pagina>
  )
}

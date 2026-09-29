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
import { useSessao } from '../lib/sessao'

export default function NovoPedido() {
  const { segmentos, erro: erroApoio } = useApoio()
  const sessao = useSessao()
  const navegar = useNavigate()
  const [cliente, setCliente] = useState('')
  const [site, setSite] = useState('')
  const [segmento, setSegmento] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  async function enviar(ev: React.FormEvent) {
    ev.preventDefault()
    setErro(null)
    if (!cliente.trim() || !site.trim()) {
      setErro('Informe o cliente e o site.')
      return
    }
    setEnviando(true)
    try {
      const r = await acionar('pedido_abrir', { cliente: cliente.trim(), site: site.trim(), segmento })
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
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Executivo</span>
            <span className="text-sm" style={{ color: 'var(--color-text)' }}>{sessao.executivo} · {sessao.email}</span>
          </div>
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

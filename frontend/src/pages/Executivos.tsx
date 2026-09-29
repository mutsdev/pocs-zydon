import { useState } from 'react'
import { UserPlus } from 'lucide-react'
import { Card } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import { ToastContainer } from '../components/ui/Toast'
import { useToast } from '../hooks/useToast'
import { Aviso, Pagina, Vazio } from '../components/app/Pagina'
import { useApoio } from '../hooks/useApoio'
import { consultar } from '../lib/mitra-api'
import type { Executivo } from '../lib/mitra-api'
import { useSessao } from '../lib/sessao'

export default function Executivos() {
  const { executivos, setExecutivos, erro } = useApoio()
  const { toasts, addToast, removeToast } = useToast()
  const admin = useSessao()
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')

  async function incluir(ev: React.FormEvent) {
    ev.preventDefault()
    const limpo = nome.trim().replace(/\s+/g, ' ')
    const correio = email.trim().toLowerCase()
    if (!limpo) { addToast('error', 'Informe o nome.'); return }
    if (!/^[^@\s]+@zydon\.com\.br$/.test(correio)) { addToast('error', 'Use o e-mail @zydon.com.br do usuário.'); return }
    const mesmoEmail = executivos.find((e) => (e.email || '').toLowerCase() === correio && e.nome !== limpo)
    if (mesmoEmail) { addToast('error', `Este e-mail já é de ${mesmoEmail.nome}.`); return }
    const parecido = executivos.find((e) => e.nome.localeCompare(limpo, 'pt-BR', { sensitivity: 'base' }) === 0)
    if (parecido && parecido.nome !== limpo) { addToast('error', `Já existe "${parecido.nome}".`); return }
    try {
      const r = await consultar<Executivo>('executivo_salvar', { nome: limpo, email: correio })
      if (!r.length) throw new Error()
      const novo = { ...r[0], pedidos: parecido?.pedidos || 0 }
      setExecutivos((l) => [...l.filter((e) => e.id !== novo.id), novo].sort((a, b) => a.nome.localeCompare(b.nome)))
      setNome(''); setEmail('')
      addToast('success', `${novo.nome} está na lista.`)
    } catch { addToast('error', 'Não foi possível salvar.') }
  }

  async function alternar(e: Executivo) {
    setExecutivos((l) => l.map((x) => (x.id === e.id ? { ...x, ativo: !e.ativo } : x)))
    try {
      const r = await consultar('executivo_ativo', { id: String(e.id), ativo: String(!e.ativo) })
      if (!r.length) throw new Error()
    } catch {
      setExecutivos((l) => l.map((x) => (x.id === e.id ? { ...x, ativo: e.ativo } : x)))
      addToast('error', 'Não foi possível salvar.')
    }
  }

  return (
    <Pagina titulo="Usuários" subtitulo="Quem pode abrir pedidos. O usuário entra com a conta Google do e-mail cadastrado aqui.">
      <ToastContainer toasts={toasts} onRemove={removeToast} />
      {erro && <Aviso tipo="danger" titulo={erro} />}
      {admin?.admin && (
        <Card className="p-5">
          <form onSubmit={incluir} className="flex flex-wrap items-end gap-3">
            <div className="w-full sm:w-64"><Input label="Nome" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Nome e sobrenome" /></div>
            <div className="w-full sm:w-64"><Input label="E-mail @zydon.com.br" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="nome@zydon.com.br" /></div>
            <Button type="submit" className="h-10"><UserPlus size={16} /> Incluir</Button>
          </form>
        </Card>
      )}
      <Card>
        {executivos.length === 0 ? (
          <Vazio titulo="Nenhum usuário cadastrado" texto={admin?.admin ? 'Inclua os nomes acima.' : 'Peça ao administrador para cadastrar os nomes.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-meta text-left" style={{ color: 'var(--color-text-secondary)' }}>
                  <th className="px-3 py-3 font-medium">Nome</th>
                  <th className="px-3 py-3 font-medium text-right">Pedidos</th>
                  <th className="px-3 py-3 font-medium">Situação</th>
                  {admin?.admin && <th className="px-3 py-3" />}
                </tr>
              </thead>
              <tbody>
                {executivos.map((e) => (
                  <tr key={e.id} style={{ borderTop: '1px solid var(--color-border)' }}>
                    <td className="px-3 py-3"><div className="leading-tight"><div className="font-medium">{e.nome}</div>{e.email && <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{e.email}</div>}</div></td>
                    <td className="px-3 py-3 text-right tabular-nums">{e.pedidos}</td>
                    <td className="px-3 py-3"><Badge variant={e.ativo ? 'success' : 'neutral'}>{e.ativo ? 'Ativo' : 'Inativo'}</Badge></td>
                    {admin?.admin && <td className="px-3 py-3 text-right"><Button size="sm" variant="ghost" onClick={() => alternar(e)}>{e.ativo ? 'Desativar' : 'Reativar'}</Button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Pagina>
  )
}

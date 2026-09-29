import { useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { BarChart3, LayoutList, LogOut, Menu, PlusCircle, Users, X } from 'lucide-react'
import { clearSession } from '../../lib/mitra-auth'
import { useSessao } from '../../lib/sessao'

const ITENS = [
  { para: '/novo', rotulo: 'Novo pedido', icone: PlusCircle },
  { para: '/pedidos', rotulo: 'Pedidos', icone: LayoutList },
  { para: '/relatorios', rotulo: 'Relatórios', icone: BarChart3 },
  { para: '/executivos', rotulo: 'Executivos', icone: Users, admin: true },
]

function Marca() {
  return (
    <div className="flex items-center gap-2 px-3 h-9">
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
        <rect width="28" height="28" rx="7" fill="var(--color-primary)" />
        <path d="M8 9h12l-12 10h12" stroke="var(--color-on-primary)" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>POCs Zydon</div>
        <div className="text-meta" style={{ color: 'var(--color-text-secondary)' }}>Portais de demonstração</div>
      </div>
    </div>
  )
}

function Navegacao({ aoNavegar }: { aoNavegar?: () => void }) {
  const navegar = useNavigate()
  const sessao = useSessao()
  return (
    <nav className="flex flex-col h-full w-60 p-3" style={{ backgroundColor: 'var(--color-nav)', borderRight: '1px solid var(--color-border)' }}>
      <Marca />
      <div className="flex flex-col gap-1 mt-4">
        {ITENS.filter((i) => !('admin' in i) || sessao.admin).filter((i) => i.para !== '/novo' || sessao.executivo_id).map(({ para, rotulo, icone: Icone }) => (
          <NavLink
            key={para}
            to={para}
            onClick={aoNavegar}
            className="flex items-center gap-2 h-9 px-3 rounded-md text-sm cursor-pointer transition-colors"
            style={({ isActive }) => ({
              backgroundColor: isActive ? 'var(--color-primary-bg)' : 'transparent',
              color: isActive ? 'var(--color-primary-text)' : 'var(--color-nav-text)',
              fontWeight: isActive ? 600 : 500,
            })}
          >
            <Icone size={18} />
            {rotulo}
          </NavLink>
        ))}
      </div>
      <div className="mt-auto px-3 py-2 leading-tight">
        <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>{sessao.executivo || sessao.email}</div>
        <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{sessao.admin ? 'Administrador' : 'Executivo'}</div>
      </div>
      <button
        onClick={() => { clearSession(); navegar('/login', { replace: true }) }}
        className=" flex items-center gap-2 h-9 px-3 rounded-md text-sm cursor-pointer"
        style={{ color: 'var(--color-nav-text)' }}
      >
        <LogOut size={18} /> Sair
      </button>
    </nav>
  )
}

export default function Shell({ children }: { children: ReactNode }) {
  const [aberto, setAberto] = useState(false)
  return (
    <div className="flex h-screen overflow-hidden" style={{ backgroundColor: 'var(--color-bg)' }}>
      <aside className="hidden md:flex h-full shrink-0 overflow-y-auto"><Navegacao /></aside>
      {aberto && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="h-full"><Navegacao aoNavegar={() => setAberto(false)} /></div>
          <button aria-label="Fechar menu" className="flex-1 cursor-pointer" style={{ backgroundColor: 'var(--color-scrim)' }} onClick={() => setAberto(false)} />
        </div>
      )}
      <main className="flex-1 overflow-y-auto">
        <div className="md:hidden sticky top-0 z-40 flex items-center justify-between h-14 px-4" style={{ backgroundColor: 'var(--color-surface)', borderBottom: '1px solid var(--color-border)' }}>
          <Marca />
          <button aria-label="Abrir menu" className="h-10 w-10 flex items-center justify-center cursor-pointer" onClick={() => setAberto(true)} style={{ color: 'var(--color-text)' }}>
            {aberto ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
        {children}
      </main>
    </div>
  )
}

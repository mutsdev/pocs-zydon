import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { initMitra, mitra } from './lib/mitra-auth'
import LoginPage from './pages/LoginPage'
import Shell from './components/app/Shell'
import NovoPedido from './pages/NovoPedido'
import Pedidos from './pages/Pedidos'
import PedidoDetalhe from './pages/PedidoDetalhe'
import Relatorios from './pages/Relatorios'
import Executivos from './pages/Executivos'
import Barrado from './components/app/Barrado'
import { SessaoContexto } from './lib/sessao'
import type { Sessao } from './lib/sessao'
import { consultar } from './lib/mitra-api'

function App() {
  // Espera o initMitra resolver a sessão antes de decidir as rotas:
  // null = resolvendo (nada renderiza — sem piscar a tela de login no preview).
  const [configured, setConfigured] = useState<boolean | null>(null)

  useEffect(() => {
    let active = true
    let unsubscribeAuth: (() => void) | undefined

    initMitra()
      .then((authenticated) => {
        if (!active) return
        setConfigured(authenticated)
        unsubscribeAuth = mitra.auth.onAuthStateChange((user) => {
          if (active) setConfigured(user !== null)
        })
      })
      .catch(() => {
        if (active) setConfigured(false)
      })

    return () => {
      active = false
      unsubscribeAuth?.()
    }
  }, [])

  const [sessao, setSessao] = useState<Sessao | null | 'erro' | 'carregando'>('carregando')
  useEffect(() => {
    if (!configured) { setSessao('carregando'); return }
    let ativo = true
    consultar<Sessao>('sessao')
      .then((r) => { if (ativo) setSessao(r[0] || null) })
      .catch(() => { if (ativo) setSessao('erro') })
    return () => { ativo = false }
  }, [configured])

  if (configured === null) return null
  if (configured && sessao === 'carregando') return null
  if (configured && sessao === 'erro') return <Barrado titulo="Não foi possível verificar o acesso" texto="Tente entrar de novo em alguns instantes." />
  if (configured && (sessao === null || !(sessao as Sessao).dominio_ok)) {
    return <Barrado titulo="Acesso restrito à equipe Zydon" texto="Entre com a sua conta Google @zydon.com.br." email={(sessao as Sessao | null)?.email} />
  }
  const s = configured ? (sessao as Sessao) : null
  if (s && !s.admin && !s.executivo_id) {
    return <Barrado titulo="Seu acesso ainda não foi liberado" texto="Peça ao João Pedro para te cadastrar." email={s.email} />
  }

  return (
    <SessaoContexto.Provider value={s}>
    <Routes>
      {configured ? (
        <>
          <Route path="/" element={<Navigate to={s?.executivo_id ? '/novo' : '/pedidos'} replace />} />
          <Route path="/novo" element={<Shell><NovoPedido /></Shell>} />
          <Route path="/pedidos" element={<Shell><Pedidos /></Shell>} />
          <Route path="/pedidos/:id" element={<Shell><PedidoDetalhe /></Shell>} />
          <Route path="/relatorios" element={<Shell><Relatorios /></Shell>} />
          {s?.admin && <Route path="/executivos" element={<Shell><Executivos /></Shell>} />}
        </>
      ) : <Route path="/" element={<Navigate to="/login" replace />} />}
      <Route path="/login" element={<LoginPage onLogin={() => setConfigured(true)} />} />
      {/* Catch-all: rota desconhecida volta pra home. */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </SessaoContexto.Provider>
  )
}

export default App

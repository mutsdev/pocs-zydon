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

  if (configured === null) return null

  return (
    <Routes>
      {configured ? (
        <>
          <Route path="/" element={<Navigate to="/pedidos" replace />} />
          <Route path="/novo" element={<Shell><NovoPedido /></Shell>} />
          <Route path="/pedidos" element={<Shell><Pedidos /></Shell>} />
          <Route path="/pedidos/:id" element={<Shell><PedidoDetalhe /></Shell>} />
          <Route path="/relatorios" element={<Shell><Relatorios /></Shell>} />
          <Route path="/executivos" element={<Shell><Executivos /></Shell>} />
        </>
      ) : <Route path="/" element={<Navigate to="/login" replace />} />}
      <Route path="/login" element={<LoginPage onLogin={() => setConfigured(true)} />} />
      {/* Catch-all: rota desconhecida volta pra home. */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App

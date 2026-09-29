import { Lock, LogOut } from 'lucide-react'
import { Card } from '../ui/Card'
import Button from '../ui/Button'
import { clearSession } from '../../lib/mitra-auth'

export default function Barrado({ titulo, texto, email }: { titulo: string; texto: string; email?: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ backgroundColor: 'var(--color-bg)' }}>
      <Card className="w-full max-w-md p-6 flex flex-col items-center text-center gap-3">
        <div className="h-12 w-12 rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--color-warning-bg)', color: 'var(--color-warning)' }}><Lock size={22} /></div>
        <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>{titulo}</h1>
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{texto}</p>
        {email && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Conectado como {email}</p>}
        <Button variant="secondary" onClick={() => { clearSession(); window.location.assign('/login') }}><LogOut size={16} /> Sair e entrar com outra conta</Button>
      </Card>
    </div>
  )
}

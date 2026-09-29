import { createContext, useContext } from 'react'

export interface Sessao { email: string; dominio_ok: boolean; admin: boolean; executivo_id: number | null; executivo: string | null; cargo?: string | null }

export const SessaoContexto = createContext<Sessao | null>(null)

export function useSessao(): Sessao {
  const s = useContext(SessaoContexto)
  if (!s) throw new Error('sessão ausente')
  return s
}

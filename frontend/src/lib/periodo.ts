const iso = (d: Date) => d.toISOString().slice(0, 10)

export const PERIODOS = [
  { value: '', label: 'Todo o período' },
  { value: '7', label: 'Últimos 7 dias' },
  { value: '30', label: 'Últimos 30 dias' },
  { value: '90', label: 'Últimos 90 dias' },
  { value: 'mes', label: 'Este mês' },
  { value: 'mes_anterior', label: 'Mês anterior' },
]

export function intervalo(periodo: string): { desde: string; ate: string } {
  const hoje = new Date()
  if (!periodo) return { desde: '', ate: '' }
  if (periodo === 'mes') return { desde: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), ate: iso(hoje) }
  if (periodo === 'mes_anterior') {
    return { desde: iso(new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1)), ate: iso(new Date(hoje.getFullYear(), hoje.getMonth(), 0)) }
  }
  const desde = new Date(hoje)
  desde.setDate(hoje.getDate() - Number(periodo) + 1)
  return { desde: iso(desde), ate: iso(hoje) }
}

import type { Status } from './mitra-api'

export const STATUS: Record<Status, { rotulo: string; variante: 'success' | 'danger' | 'info' | 'warning' | 'neutral' }> = {
  na_fila: { rotulo: 'Na fila', variante: 'neutral' },
  extraindo: { rotulo: 'Buscando produtos', variante: 'info' },
  aguardando_anexo: { rotulo: 'Recebendo anexo', variante: 'info' },
  curadoria: { rotulo: 'Em curadoria', variante: 'warning' },
  precisa_catalogo: { rotulo: 'Precisa de catálogo', variante: 'warning' },
  criando: { rotulo: 'Criando portal', variante: 'info' },
  concluido: { rotulo: 'Concluído', variante: 'success' },
  falhou: { rotulo: 'Falhou', variante: 'danger' },
}

export const OPCOES_STATUS = Object.entries(STATUS).map(([value, s]) => ({ value, label: s.rotulo }))

export const PRECO: Record<string, { rotulo: string; variante: 'success' | 'warning' | 'danger' | 'neutral' }> = {
  publico: { rotulo: 'Preço público', variante: 'success' },
  estimado: { rotulo: 'Preço estimado', variante: 'warning' },
  ausente: { rotulo: 'Sem preço', variante: 'danger' },
}

export const FONTE: Record<string, string> = { site: 'Site', pdf: 'PDF', planilha: 'Planilha', busca: 'Busca na web' }

export const BANNERS: Record<string, string> = {
  gerando: 'Gerando banners', prontos: 'Banners prontos', regerando: 'Refazendo banners', aplicando: 'Aplicando banners',
  aplicado: 'Banners aplicados', aplicado_parcial: 'Banners aplicados em parte', dispensado: 'Banners dispensados',
  sem_banner: 'Sem banner', falhou: 'Banners falharam',
}

const data = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
export const dataHora = (v: string | null) => (v ? data.format(new Date(v)) : '—')

const moeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
export const reais = (v: number | null | undefined) => (v === null || v === undefined ? '—' : moeda.format(v))

export const dolares = (v: number | string | null | undefined) =>
  v === null || v === undefined ? '—' : `US$ ${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`

export function duracao(segundos: number | null | undefined) {
  if (segundos === null || segundos === undefined) return '—'
  const s = Math.round(Number(segundos))
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ${s % 60} s`
  return `${Math.floor(m / 60)} h ${m % 60} min`
}

import { acionar, consultar, ErroApi } from './mitra-api'

export const ACEITOS = '.pdf,.xlsx,.xls,.csv,.docx'
export const LIMITE_BYTES = 15 * 1024 * 1024
const PARTE = 500000

export function validarArquivo(arquivo: File): string | null {
  if (!/\.(pdf|xlsx|xls|csv|docx)$/i.test(arquivo.name)) return 'Envie PDF, planilha (xlsx, xls, csv) ou Word (docx).'
  if (arquivo.size > LIMITE_BYTES) return 'O arquivo passa de 15 MB. Envie uma versão menor.'
  return null
}

function paraBase64(arquivo: File): Promise<string> {
  return new Promise((ok, falha) => {
    const leitor = new FileReader()
    leitor.onload = () => ok(String(leitor.result).split(',')[1] || '')
    leitor.onerror = () => falha(new ErroApi('LEITURA', 'Não foi possível ler o arquivo.'))
    leitor.readAsDataURL(arquivo)
  })
}

export async function enviarAnexo(pedidoId: string, arquivo: File, aoProgresso?: (fracao: number) => void) {
  const conteudo = await paraBase64(arquivo)
  const total = Math.max(1, Math.ceil(conteudo.length / PARTE))
  for (let i = 0; i < total; i += 1) {
    const r = await consultar('anexo_parte', { pedido_id: pedidoId, parte: String(i), conteudo: conteudo.slice(i * PARTE, (i + 1) * PARTE) })
    if (!r.length) throw new ErroApi('ANEXO_RECUSADO', 'O pedido não aceita anexo agora. Atualize a página e tente de novo.')
    aoProgresso?.((i + 1) / total)
  }
  await acionar('pedido_acao', { pedido_id: pedidoId, acao: 'extrair', anexo_nome: arquivo.name, anexo_partes: total })
}

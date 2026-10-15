import { mitra } from './mitra-auth'
import { SF } from './sf-ids'
import type { SfNome } from './sf-ids'

export class ErroApi extends Error {
  codigo: string
  detalhe: Record<string, unknown>
  constructor(codigo: string, mensagem: string, detalhe: Record<string, unknown> = {}) {
    super(mensagem)
    this.codigo = codigo
    this.detalhe = detalhe
  }
}

function normalizar(saida: unknown): Record<string, unknown> {
  if (typeof saida === 'string') {
    try { return JSON.parse(saida) } catch { return { valor: saida } }
  }
  return (saida as Record<string, unknown>) || {}
}

function mensagemAmigavel(texto: string, padrao: string) {
  if (/rate limit|429/i.test(texto || '')) return 'Muita gente usando ao mesmo tempo. Espere alguns segundos e tente de novo.'
  if (/network|fetch|failed/i.test(texto || '')) return 'A conexão falhou. Confira a internet e tente de novo.'
  return padrao
}

function conferir(execucao: { status: string; errorMessage: string | null; output: unknown }) {
  if (execucao.status !== 'SUCCESS') {
    const bruta = execucao.errorMessage || 'A operação não foi concluída.'
    throw new ErroApi('FALHA_EXECUCAO', mensagemAmigavel(bruta, 'A operação não foi concluída. Tente de novo.'))
  }
  return normalizar(execucao.output)
}

export async function consultar<T>(nome: SfNome, entrada: Record<string, string> = {}): Promise<T[]> {
  const execucao = await mitra.functions.execute(SF[nome], entrada)
  const saida = conferir(execucao)
  return (saida.rows as T[]) || []
}

const esperar = (ms: number) => new Promise((ok) => setTimeout(ok, ms))

export async function acionar(nome: SfNome, entrada: Record<string, unknown>): Promise<Record<string, unknown>> {
  let inicio
  try {
    inicio = await mitra.functions.executeAsync(SF[nome], entrada)
  } catch (e) {
    throw new ErroApi('LIMITE_PLATAFORMA', mensagemAmigavel(e instanceof Error ? e.message : '', 'Muita gente usando ao mesmo tempo. Espere alguns segundos e tente de novo.'))
  }
  let execucao = inicio
  const limite = Date.now() + 120000
  while (['RUNNING', 'PENDING', 'QUEUED'].includes(execucao.status) && Date.now() < limite) {
    await esperar(1500)
    execucao = await mitra.functions.getExecution(inicio.id)
  }
  const saida = conferir(execucao)
  if (saida.ok === false) {
    throw new ErroApi(String(saida.erro || 'ERRO'), mensagemDeErro(saida), saida)
  }
  return saida
}

const MENSAGENS: Record<string, string> = {
  CAMPOS_FALTANDO: 'Preencha os campos obrigatórios',
  SITE_INVALIDO: 'O endereço do site não é válido.',
  EXECUTIVO_DESCONHECIDO: 'Usuário não encontrado ou inativo.',
  PEDIDO_DESCONHECIDO: 'Pedido não encontrado.',
  STATUS_NAO_PERMITE: 'O status atual do pedido não permite esta ação.',
  EM_EXECUCAO: 'Este pedido já tem uma etapa em andamento. Aguarde terminar.',
  PORTAL_AUSENTE: 'O portal ainda não foi criado.',
  PIPELINE_AUSENTE: 'O serviço de criação está indisponível.',
  ACAO_INVALIDA: 'Ação inválida.',
  ANEXO_INVALIDO: 'Envie PDF, planilha (xlsx, xls, csv) ou Word (docx).',
  ANEXO_AUSENTE: 'O arquivo chegou incompleto. Envie de novo.',
  LOGO_FORMATO: 'Envie a logo em PNG, JPG, SVG ou WEBP.',
  LOGO_RECUSADA: 'O pedido não aceita trocar a logo agora.',
  EXECUTIVO_NAO_CADASTRADO: 'Peça ao João Pedro para te cadastrar.',
  CAMPOS_FALTANDO_EXECUTIVO: 'Escolha para qual usuário é o portal.',
  SO_ADMIN: 'Só o administrador pode fazer isso.',
  TOKEN_DESCONHECIDO: 'Token não encontrado ou já revogado.',
  LOTE_GRANDE: 'Envie no máximo 50 empresas por vez.',
  PLANILHA_FORMATO: 'Envie a planilha em xlsx ou csv (xls antigo: salve como xlsx).',
  PLANILHA_GRANDE: 'A planilha é grande demais. Envie até 2 MB.',
  PLANILHA_ILEGIVEL: 'Não consegui ler a planilha. Salve de novo em xlsx ou csv.',
  PLANILHA_VAZIA: 'A planilha está vazia.',
  NENHUMA_VALIDA: 'Nenhuma empresa válida: confira nome e site de cada linha.',
  LIMITE_PLATAFORMA: 'Muita gente usando ao mesmo tempo. Espere alguns segundos e tente de novo.',
  SEM_SESSAO: 'Sua sessão expirou. Saia e entre de novo.',
  ACESSO_RESTRITO: 'Acesso restrito à equipe Zydon.',
}

function mensagemDeErro(saida: Record<string, unknown>) {
  const codigo = String(saida.erro || '')
  const base = MENSAGENS[codigo] || codigo || 'Erro desconhecido.'
  if (codigo === 'CAMPOS_FALTANDO' && Array.isArray(saida.faltando) && saida.faltando.includes('executivo')) return MENSAGENS.CAMPOS_FALTANDO_EXECUTIVO
  if (codigo === 'CAMPOS_FALTANDO' && Array.isArray(saida.faltando)) return `${base}: ${saida.faltando.join(', ')}.`
  return base
}

export type Status = 'na_fila' | 'extraindo' | 'aguardando_anexo' | 'curadoria' | 'precisa_catalogo' | 'criando' | 'concluido' | 'falhou'

export interface Executivo { id: number; nome: string; email: string | null; cargo: string | null; ativo: boolean; pedidos: number }

export interface PedidoLinha {
  pedido_id: string; cliente: string; site: string; status: Status; segmento: string | null
  segmento_origem: string | null; foco?: string | null; executivo: string; produtos: number | null; preco: string | null
  fonte: string | null; portal_url: string | null; banners_situacao: string | null; erro_codigo: string | null
  produtos_similares: boolean; simulado: boolean; criado_em: string; concluido_em: string | null
  execucao_acao: string | null; em_execucao: boolean
}

export interface PerguntaTelufia {
  ordem: number; pergunta: string; objetivo: string | null; dor: string | null; produto: string | null
}

export interface Pedido extends PedidoLinha {
  executivo_id: number; commit_codigo: string; categorias: number | null; logo_url: string | null
  catalogo: string | null; resumo: string | null; portal_id: string | null; banner_cor: string | null
  observacoes: string | null; erro: string | null; motivo_catalogo: string | null; modelo_ia: string | null
  custo_ia_usd: number | string; tokens_ia: number; extracao_fim: string | null; curadoria_fim: string | null
  criacao_inicio: string | null; falhou_em: string | null; execucao_desde: string | null
  anexo_nome: string | null; nomes_lidos_na_imagem: number | null
  acao_desde: string | null; logo_origem: string | null; logo_aviso: string | null; logo_previa: string | null; telufia?: string | null
}

export interface Evento { id: number; etapa: string; mensagem: string; nivel: string; criado_em: string }

export interface Peca {
  id: number; peca: string; geracao: number; file_id: string | null; url: string | null; cor: string | null
  aplicada: boolean; conferida_get: boolean; previa_base64: string | null
}

export interface LinhaRelatorio {
  dimensao: string; valor: string; pedidos: number; concluidos: number; falharam: number; em_curadoria: number
  precisa_catalogo: number; em_andamento: number; tempo_medio_s: number | null; tempo_criacao_s: number | null
  produtos_medio: number | null; custo_ia_usd: number | null
}

export interface Filtros { executivo: string; segmento: string; status: string; desde: string; ate: string }

export const FILTROS_VAZIOS: Filtros = { executivo: '', segmento: '', status: '', desde: '', ate: '' }

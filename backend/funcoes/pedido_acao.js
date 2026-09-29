// Dispara uma acao da pipeline para um pedido existente, em segundo plano.
// Acoes aceitas: criar (com simular opcional), banner (dispensar | aplicar | regerar), extrair (refazer).
const { createClient } = require('@mitralab.io/functions-sdk');

const PERMITIDAS = {
  criar: ['curadoria'],
  extrair: ['falhou', 'precisa_catalogo'],
  banner: ['curadoria', 'concluido'],
};
const ACOES_BANNER = ['dispensar', 'aplicar', 'regerar'];

__GUARDA__

module.exports = async (event, context) => {
  const ev = (event && event.input) ? event.input : (event || {});
  const mitra = createClient();
  await mitra.init();
  const g = await guarda(mitra, context);
  if (!g.ok) return g;
  const pedidoId = String(ev.pedido_id || '').trim();
  const acao = String(ev.acao || '').trim();
  const faltando = [];
  if (!pedidoId) faltando.push('pedido_id');
  if (!acao) faltando.push('acao');
  if (faltando.length) return { ok: false, erro: 'CAMPOS_FALTANDO', faltando };
  if (!PERMITIDAS[acao]) return { ok: false, erro: 'ACAO_INVALIDA', acao };
  if (acao === 'banner' && !ACOES_BANNER.includes(ev.acao_banner)) {
    return { ok: false, erro: 'ACAO_INVALIDA', acao_banner: ev.acao_banner || null };
  }

  const sql = async (q, p = {}) => (await mitra.sql.executeQuery(q, p)).rows || [];
  const linhas = await sql(`SELECT status, portal_id, execucao_atual, execucao_desde FROM pedidos
    WHERE pedido_id = :p AND (CAST(:adm AS BOOLEAN) OR executivo_id = CAST(NULLIF(:ex, '') AS INTEGER))`,
    { p: pedidoId, adm: String(g.sessao.admin), ex: g.sessao.executivo_id ? String(g.sessao.executivo_id) : '' });
  if (!linhas.length) return { ok: false, erro: 'PEDIDO_DESCONHECIDO', pedido_id: pedidoId };
  const pedido = linhas[0];
  if (!PERMITIDAS[acao].includes(pedido.status)) {
    return { ok: false, erro: 'STATUS_NAO_PERMITE', status: pedido.status, acao };
  }
  if (acao === 'banner' && ev.acao_banner === 'aplicar' && !pedido.portal_id) {
    return { ok: false, erro: 'PORTAL_AUSENTE' };
  }
  if (pedido.execucao_atual) return { ok: false, erro: 'EM_EXECUCAO', desde: pedido.execucao_desde };

  const entrada = { acao, pedido_id: pedidoId };
  if (acao === 'criar') entrada.simular = !!ev.simular;
  if (acao === 'banner') {
    entrada.acao_banner = ev.acao_banner;
    for (const k of ['escolhas', 'pecas', 'feedback', 'cor']) if (ev[k] !== undefined) entrada[k] = ev[k];
  }
  const lista = await mitra.functionsAdmin.list({ size: 100 });
  const pipeline = (lista.content || lista.items || []).find((f) => f.name === 'pipeline_poc');
  if (!pipeline) return { ok: false, erro: 'PIPELINE_AUSENTE' };
  const execucao = await mitra.functions.executeAsync(pipeline.id, entrada);
  return { ok: true, pedido_id: pedidoId, acao, execucao: execucao.id };
};

// Admin: apaga um pedido e tudo o que depende dele (eventos, arquivos, peças de banner, feedback), numa transação.
// Recusa pedido com etapa em andamento recente, para a pipeline não regravar o que foi apagado.
const { createClient } = require('@mitralab.io/functions-sdk');

__GUARDA__

module.exports = async (event, context) => {
  const ev = (event && event.input) ? event.input : (event || {});
  const mitra = createClient();
  await mitra.init();
  const g = await guarda(mitra, context);
  if (!g.ok) return g;
  if (!g.sessao.admin) return { ok: false, erro: 'SO_ADMIN' };
  const pedidoId = String(ev.pedido_id || '').trim();
  if (!pedidoId) return { ok: false, erro: 'CAMPOS_FALTANDO', faltando: ['pedido_id'] };

  const linhas = (await mitra.sql.executeQuery(`SELECT pedido_id,
      (execucao_atual IS NOT NULL AND COALESCE(execucao_desde, atualizado_em) > now() - INTERVAL '30 minutes') AS rodando
    FROM pedidos WHERE pedido_id = :p`, { p: pedidoId })).rows || [];
  if (!linhas.length) return { ok: false, erro: 'PEDIDO_DESCONHECIDO', pedido_id: pedidoId };
  if (linhas[0].rodando && !ev.forcar) return { ok: false, erro: 'EM_EXECUCAO' };

  const p = { p: pedidoId };
  await mitra.sql.executeDml([
    { sql: 'DELETE FROM pecas_banner WHERE pedido_id = :p', parameters: p },
    { sql: 'DELETE FROM pedido_arquivos WHERE pedido_id = :p', parameters: p },
    { sql: 'DELETE FROM pedido_eventos WHERE pedido_id = :p', parameters: p },
    { sql: 'DELETE FROM feedback_banner WHERE pedido_id = :p', parameters: p },
    { sql: 'UPDATE travas SET pedido_id = NULL, execucao_id = NULL WHERE pedido_id = :p', parameters: p },
    { sql: 'DELETE FROM pedidos WHERE pedido_id = :p', parameters: p },
  ]);
  return { ok: true, pedido_id: pedidoId };
};

// Admin do Dexter: lote pela tela, tokens de API (gerar/revogar) e controle da fila (retentar/cancelar).
const { createClient } = require('@mitralab.io/functions-sdk');
const crypto = require('crypto');

__GUARDA__
__DEXTER__

module.exports = async (event, context) => {
  const ev = (event && event.input) ? event.input : (event || {});
  const mitra = createClient();
  await mitra.init();
  const g = await guarda(mitra, context);
  if (!g.ok) return g;
  if (!g.sessao.admin) return { ok: false, erro: 'SO_ADMIN', mensagem: 'Só o administrador controla o Dexter.' };
  const sql = async (q, p = {}) => (await mitra.sql.executeQuery(q, p)).rows || [];
  const dml = (q, p = {}) => mitra.sql.executeDml([{ sql: q, parameters: p }]);
  const acao = String(ev.acao || '');

  if (acao === 'lote') {
    const alvo = ev.executivo_id ? String(ev.executivo_id) : '';
    const dono = (await sql(`SELECT id, nome FROM executivos WHERE ativo AND
      (CASE WHEN :e = '' THEN cargo = 'Agente de prospecção' ELSE id = CAST(NULLIF(:e, '') AS INTEGER) END) ORDER BY id LIMIT 1`, { e: alvo }))[0];
    if (!dono) return { ok: false, erro: 'EXECUTIVO_DESCONHECIDO' };
    return abrirLote(mitra, dono, ev.empresas, { nome: ev.nome, origem: 'tela' });
  }

  if (acao === 'gerar_token') {
    const dono = (await sql('SELECT id, nome FROM executivos WHERE id = CAST(:e AS INTEGER) AND ativo', { e: String(ev.executivo_id || 0) }))[0];
    if (!dono) return { ok: false, erro: 'EXECUTIVO_DESCONHECIDO' };
    const token = `dxt_${crypto.randomBytes(24).toString('base64url')}`;
    const hash = crypto.createHash('sha256').update(token).digest('hex');
    const linha = await sql(`INSERT INTO tokens_api (executivo_id, token_hash, prefixo) VALUES (CAST(:e AS INTEGER), :h, :p)
      RETURNING id, prefixo, criado_em`, { e: String(dono.id), h: hash, p: token.slice(0, 10) });
    return { ok: true, token, id: linha[0].id, prefixo: linha[0].prefixo, criado_em: linha[0].criado_em, usuario: dono.nome };
  }

  if (acao === 'revogar_token') {
    const r = await sql(`UPDATE tokens_api SET revogado_em = now() WHERE id = CAST(:i AS INTEGER) AND revogado_em IS NULL RETURNING id, revogado_em`,
      { i: String(ev.id || 0) });
    return r.length ? { ok: true, ...r[0] } : { ok: false, erro: 'TOKEN_DESCONHECIDO' };
  }

  if (acao === 'retentar' || acao === 'cancelar') {
    const pedidoId = String(ev.pedido_id || '').trim();
    const r = acao === 'retentar'
      ? await sql(`UPDATE pedidos SET status = 'na_fila', erro = NULL, erro_codigo = NULL, motivo_catalogo = NULL,
          execucao_atual = NULL, atualizado_em = now()
        WHERE pedido_id = :p AND automatico AND portal_id IS NULL AND status IN ('falhou', 'precisa_catalogo') RETURNING pedido_id, status`, { p: pedidoId })
      : await sql(`UPDATE pedidos SET status = 'falhou', erro = 'cancelado pelo administrador', erro_codigo = 'CANCELADO',
          falhou_em = now(), atualizado_em = now()
        WHERE pedido_id = :p AND automatico AND status = 'na_fila' RETURNING pedido_id, status`, { p: pedidoId });
    if (!r.length) return { ok: false, erro: 'STATUS_NAO_PERMITE', acao };
    await dml(`INSERT INTO pedido_eventos (pedido_id, etapa, mensagem) VALUES (:p, 'dexter', :m)`,
      { p: pedidoId, m: acao === 'retentar' ? 'de volta para a fila pelo administrador' : 'cancelado pelo administrador' });
    if (acao === 'retentar') await acordarDespacho(mitra);
    return { ok: true, ...r[0] };
  }

  if (acao === 'despachar') return { ok: await acordarDespacho(mitra) };
  return { ok: false, erro: 'ACAO_INVALIDA', acao };
};

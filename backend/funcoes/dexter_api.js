// API publica do Dexter: cria lotes de portais sem curadoria e consulta o andamento.
// Autenticacao: token por usuario no corpo ({ "token": "dxt_..." }); o banco guarda so o hash SHA-256.
const { createClient } = require('@mitralab.io/functions-sdk');
const crypto = require('crypto');

__GUARDA__
__DEXTER__

function lerCorpo(event) {
  let corpo = event && event.input !== undefined ? event.input : event;
  if (corpo && typeof corpo.body === 'string') corpo = corpo.body;
  if (typeof corpo === 'string') {
    try { corpo = JSON.parse(corpo); } catch (e) { return null; }
  }
  return corpo && typeof corpo === 'object' ? corpo : null;
}

module.exports = async (event) => {
  const corpo = lerCorpo(event);
  if (!corpo) return { ok: false, erro: 'JSON_INVALIDO', mensagem: 'Envie um corpo JSON.' };
  const token = String(corpo.token || '').trim();
  if (!token) return { ok: false, erro: 'TOKEN_AUSENTE', mensagem: 'Envie o token no campo "token".' };
  const mitra = paciente(createClient());
  await mitra.init();
  const hash = crypto.createHash('sha256').update(token).digest('hex');
  const dono = ((await mitra.sql.executeQuery(`SELECT t.id AS token_id, e.id, e.nome FROM tokens_api t
      JOIN executivos e ON e.id = t.executivo_id AND e.ativo
    WHERE t.token_hash = :h AND t.revogado_em IS NULL`, { h: hash })).rows || [])[0];
  if (!dono) return { ok: false, erro: 'TOKEN_INVALIDO', mensagem: 'Token inválido, revogado ou de usuário desativado.' };
  await mitra.sql.executeDml([{ sql: 'UPDATE tokens_api SET ultimo_uso = now() WHERE id = CAST(:i AS INTEGER)', parameters: { i: String(dono.token_id) } }]);

  const acao = String(corpo.acao || (corpo.pedido_id || corpo.lote_id || corpo.referencia_consulta ? 'andamento' : 'criar'));
  if (acao === 'andamento') {
    return andamentoDexter(mitra, dono.id, { ...corpo, referencia: corpo.referencia_consulta || (corpo.empresas ? null : corpo.referencia) });
  }
  if (acao === 'criar') {
    const empresas = Array.isArray(corpo.empresas) ? corpo.empresas : [corpo];
    const r = await abrirLote(mitra, dono, empresas, { nome: corpo.lote, origem: 'api' });
    return { ...r, usuario: dono.nome };
  }
  return { ok: false, erro: 'ACAO_INVALIDA', mensagem: 'Use "criar" ou "andamento".' };
};

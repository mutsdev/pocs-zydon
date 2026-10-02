// Despertador da fila do Dexter (cron a cada 5 min): acorda o despacho da pipeline_poc, que solta os pedidos parados na fila.
const { createClient } = require('@mitralab.io/functions-sdk');

__GUARDA__
__DEXTER__

module.exports = async () => {
  const mitra = paciente(createClient());
  await mitra.init();
  const fila = ((await mitra.sql.executeQuery(`SELECT count(*) AS n FROM pedidos WHERE automatico AND status = 'na_fila'`, {})).rows || [])[0];
  const semLink = ((await mitra.sql.executeQuery(`SELECT count(*) AS n FROM pedidos WHERE status = 'falhou' AND portal_id IS NOT NULL
    AND portal_url IS NULL AND erro LIKE '%nenhum portal chamado%' AND erro NOT LIKE '%pelo id%'`, {})).rows || [])[0];
  const vencidos = ((await mitra.sql.executeQuery(`SELECT count(*) AS n FROM pedidos WHERE automatico AND status = 'concluido'
    AND portal_id IS NOT NULL AND loja_desativada_em IS NULL AND concluido_em < now() - interval '15 days'`, {})).rows || [])[0];
  const n = Number((fila && fila.n) || 0), s = Number((semLink && semLink.n) || 0), v = Number((vencidos && vencidos.n) || 0);
  if (!n && !s && !v) return { ok: true, na_fila: 0 };
  return { ok: await acordarDespacho(mitra), na_fila: n, sem_link: s, lojas_a_desativar: v };
};

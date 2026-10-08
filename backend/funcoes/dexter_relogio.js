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
  try {
    await mitra.sql.executeDml([{ sql: `DELETE FROM pedido_arquivos WHERE tipo = 'banners' AND pedido_id IN (SELECT pedido_id FROM pedidos
      WHERE status = 'concluido' AND banners_situacao = 'aplicado' AND concluido_em < now() - interval '7 days')`, parameters: {} }]);
  } catch (e) { /* limpa no próximo ciclo */ }
  const n = Number((fila && fila.n) || 0), s = Number((semLink && semLink.n) || 0), v = Number((vencidos && vencidos.n) || 0);
  const lab = ((await mitra.sql.executeQuery(`SELECT count(*) AS n FROM banner_lab WHERE situacao = 'na_fila'`, {})).rows || [])[0];
  const l = Number((lab && lab.n) || 0);
  let labAcordado = false;
  if (l) {
    try {
      const chave = await chaveInternaDexter(mitra);
      const lista = await mitra.functionsAdmin.list({ size: 100 });
      const pipeline = (lista.content || lista.items || []).find((f) => f.name === 'pipeline_poc');
      if (pipeline && chave) {
        await mitra.functions.executeAsync(pipeline.id, { acao: 'lab_despachar', chave_interna: chave });
        labAcordado = true;
      }
    } catch (e) { /* tenta de novo no próximo ciclo */ }
  }
  if (!n && !s && !v) return { ok: true, na_fila: 0, lab_na_fila: l, lab_acordado: labAcordado };
  return { ok: await acordarDespacho(mitra), na_fila: n, sem_link: s, lojas_a_desativar: v };
};

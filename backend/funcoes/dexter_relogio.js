// Despertador da fila do Dexter (cron a cada 5 min): acorda o despacho da pipeline_poc, que solta os pedidos parados na fila.
const { createClient } = require('@mitralab.io/functions-sdk');

__GUARDA__
__DEXTER__

module.exports = async () => {
  const mitra = paciente(createClient());
  await mitra.init();
  const fila = ((await mitra.sql.executeQuery(`SELECT count(*) AS n FROM pedidos WHERE automatico AND status = 'na_fila'`, {})).rows || [])[0];
  if (!fila || !Number(fila.n)) return { ok: true, na_fila: 0 };
  return { ok: await acordarDespacho(mitra), na_fila: Number(fila.n) };
};

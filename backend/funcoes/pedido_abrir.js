// Abre um pedido de POC: valida os campos, gera o pedido_id, grava e dispara a pipeline em segundo plano.
const { createClient } = require('@mitralab.io/functions-sdk');

const COMMIT = '7b3d073427e47ecf660280920bfba23c3178834a';

module.exports = async (event, context) => {
  const ev = (event && event.input) ? event.input : (event || {});
  const texto = (v) => (v === undefined || v === null ? '' : String(v)).trim();
  const campos = { executivo: texto(ev.executivo), cliente: texto(ev.cliente), site: texto(ev.site) };
  const faltando = Object.keys(campos).filter((k) => !campos[k]);
  if (faltando.length) return { ok: false, erro: 'CAMPOS_FALTANDO', faltando };
  let site = campos.site;
  if (!/^https?:\/\//i.test(site)) site = `https://${site}`;
  try { new URL(site); } catch (e) { return { ok: false, erro: 'SITE_INVALIDO', site: campos.site }; }

  const mitra = createClient();
  await mitra.init();
  const sql = async (q, p = {}) => (await mitra.sql.executeQuery(q, p)).rows || [];
  const dml = (q, p = {}) => mitra.sql.executeDml([{ sql: q, parameters: p }]);

  const executivo = await sql('SELECT id, nome FROM executivos WHERE id = CAST(:id AS INTEGER) AND ativo', { id: campos.executivo });
  if (!executivo.length) return { ok: false, erro: 'EXECUTIVO_DESCONHECIDO', executivo: campos.executivo };

  const segmento = texto(ev.segmento);
  const usuario = (context && (context.userId || (context.user && context.user.id))) || null;
  const numero = await sql(`INSERT INTO contador_pedidos (dia, ultimo) VALUES (CAST(now() AS DATE), 1)
    ON CONFLICT (dia) DO UPDATE SET ultimo = contador_pedidos.ultimo + 1 RETURNING ultimo, to_char(dia, 'YYYY-MM-DD') AS dia`);
  const pedidoId = `poc-${numero[0].dia}-${String(numero[0].ultimo).padStart(3, '0')}`;
  await dml(`INSERT INTO pedidos (pedido_id, executivo_id, usuario_id, cliente, site, segmento, segmento_origem, status, commit_codigo)
    VALUES (:p, CAST(:e AS INTEGER), CAST(NULLIF(:u, '') AS UUID), :c, :s, NULLIF(:sg, ''), CASE WHEN :sg = '' THEN NULL ELSE 'informado' END, 'extraindo', :cm)
    ON CONFLICT (pedido_id) DO NOTHING`,
  { p: pedidoId, e: String(executivo[0].id), u: usuario || '', c: campos.cliente, s: site, sg: segmento, cm: COMMIT });
  await dml(`INSERT INTO pedido_eventos (pedido_id, etapa, mensagem) VALUES (:p, 'pedido', :m)`,
    { p: pedidoId, m: `pedido aberto por ${executivo[0].nome}: ${campos.cliente} (${site})` });

  const lista = await mitra.functionsAdmin.list({ size: 100 });
  const pipeline = (lista.content || lista.items || []).find((f) => f.name === 'pipeline_poc');
  if (!pipeline) return { ok: false, erro: 'PIPELINE_AUSENTE', pedido_id: pedidoId };
  const execucao = await mitra.functions.executeAsync(pipeline.id, { acao: 'extrair', pedido_id: pedidoId });
  return { ok: true, pedido_id: pedidoId, execucao: execucao.id, executivo: executivo[0].nome };
};

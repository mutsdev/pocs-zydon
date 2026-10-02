// Laboratorio de banners (admin e Dexter): abre rodada de 10, salva avaliacao e aprova (aplica no portal).
const { createClient } = require('@mitralab.io/functions-sdk');

__GUARDA__

const TAMANHO_RODADA = 10;
const MARCAS = ['logo', 'cores', 'produto', 'composicao', 'texto', 'amador'];

module.exports = async (event, context) => {
  const ev = (event && event.input) ? event.input : (event || {});
  const mitra = createClient();
  await mitra.init();
  const g = await guarda(mitra, context);
  if (!g.ok) return g;
  const agente = g.sessao.cargo === 'Agente de prospecção' && !!g.sessao.executivo_id;
  if (!g.sessao.admin && !agente) return { ok: false, erro: 'SO_ADMIN', mensagem: 'Só o administrador e o Dexter usam o laboratório.' };
  const sql = async (q, p = {}) => (await mitra.sql.executeQuery(q, p)).rows || [];
  const dml = (q, p = {}) => mitra.sql.executeDml([{ sql: q, parameters: p }]);
  const acao = String(ev.acao || '');
  const pipeline = async () => {
    const lista = await mitra.functionsAdmin.list({ size: 100 });
    return (lista.content || lista.items || []).find((f) => f.name === 'pipeline_poc');
  };

  if (acao === 'nova_rodada') {
    const aberta = await sql(`SELECT r.id FROM banner_lab_rodadas r WHERE r.situacao = 'gerando'
      AND EXISTS (SELECT 1 FROM banner_lab l WHERE l.rodada_id = r.id AND l.situacao IN ('na_fila', 'gerando'))`);
    if (aberta.length) return { ok: false, erro: 'EM_EXECUCAO', mensagem: 'A rodada atual ainda está gerando.' };
    const ultima = await sql('SELECT COALESCE(MAX(numero), 0) AS n FROM banner_lab_rodadas');
    const numero = Number(ultima[0].n) + 1;
    const regras = String(ev.regras || '').slice(0, 4000);
    const nova = await sql(`INSERT INTO banner_lab_rodadas (numero, regras) VALUES (CAST(:n AS INTEGER), :r) RETURNING id`,
      { n: String(numero), r: regras });
    const rodadaId = String(nova[0].id);
    const escolhidos = await sql(`SELECT p.pedido_id FROM pedidos p
      WHERE p.portal_id IS NOT NULL AND p.catalogo IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM banner_lab l WHERE l.pedido_id = p.pedido_id)
      ORDER BY p.id LIMIT CAST(:t AS INTEGER)`, { t: String(TAMANHO_RODADA) });
    if (!escolhidos.length) {
      await dml(`UPDATE banner_lab_rodadas SET situacao = 'fechada', fechada_em = now() WHERE id = CAST(:r AS INTEGER)`, { r: rodadaId });
      return { ok: false, erro: 'SEM_PORTAIS', mensagem: 'Todos os portais já passaram pelo laboratório.' };
    }
    for (const { pedido_id: pedidoId } of escolhidos) {
      await dml(`INSERT INTO banner_lab (rodada_id, pedido_id) VALUES (CAST(:r AS INTEGER), :p)`, { r: rodadaId, p: pedidoId });
    }
    const f = await pipeline();
    const chave = ((await sql("SELECT valor FROM configuracao WHERE chave = 'chave_interna'"))[0] || {}).valor;
    if (f && chave) await mitra.functions.executeAsync(f.id, { acao: 'lab_despachar', chave_interna: chave });
    return { ok: true, rodada: numero, banners: escolhidos.length };
  }

  if (acao === 'avaliar') {
    const labId = String(parseInt(ev.lab_id, 10) || '');
    const nota = parseInt(ev.nota, 10);
    if (!labId || !(nota >= 1 && nota <= 5)) return { ok: false, erro: 'CAMPOS_FALTANDO', faltando: ['lab_id', 'nota'] };
    if (!g.sessao.executivo_id) return { ok: false, erro: 'EXECUTIVO_NAO_CADASTRADO' };
    const marcas = (Array.isArray(ev.marcas) ? ev.marcas : []).filter((m) => MARCAS.includes(m)).join(',');
    await dml(`INSERT INTO banner_lab_avaliacoes (lab_id, executivo_id, nota, marcas, comentario)
      SELECT CAST(:l AS INTEGER), CAST(:e AS INTEGER), CAST(:n AS INTEGER), :m, NULLIF(:c, '')
      WHERE NOT EXISTS (SELECT 1 FROM banner_lab_avaliacoes WHERE lab_id = CAST(:l AS INTEGER) AND executivo_id = CAST(:e AS INTEGER))`,
    { l: labId, e: String(g.sessao.executivo_id), n: String(nota), m: marcas, c: String(ev.comentario || '').slice(0, 1000) });
    await dml(`UPDATE banner_lab_avaliacoes SET nota = CAST(:n AS INTEGER), marcas = :m, comentario = NULLIF(:c, ''), atualizado_em = now()
      WHERE lab_id = CAST(:l AS INTEGER) AND executivo_id = CAST(:e AS INTEGER)`,
    { l: labId, e: String(g.sessao.executivo_id), n: String(nota), m: marcas, c: String(ev.comentario || '').slice(0, 1000) });
    return { ok: true };
  }

  if (acao === 'aprovar') {
    const labId = String(parseInt(ev.lab_id, 10) || '');
    const linha = await sql(`SELECT l.id, l.pedido_id, l.situacao, p.portal_id FROM banner_lab l JOIN pedidos p ON p.pedido_id = l.pedido_id
      WHERE l.id = CAST(:l AS INTEGER)`, { l: labId });
    if (!linha.length) return { ok: false, erro: 'PEDIDO_DESCONHECIDO' };
    if (linha[0].situacao !== 'pronto') return { ok: false, erro: 'STATUS_NAO_PERMITE', status: linha[0].situacao };
    if (!linha[0].portal_id) return { ok: false, erro: 'PORTAL_AUSENTE' };
    const f = await pipeline();
    if (!f) return { ok: false, erro: 'PIPELINE_AUSENTE' };
    await dml(`UPDATE banner_lab SET situacao = 'aplicando', aprovado_por = CAST(NULLIF(:e, '') AS INTEGER) WHERE id = CAST(:l AS INTEGER)`,
      { l: labId, e: g.sessao.executivo_id ? String(g.sessao.executivo_id) : '' });
    const chave = ((await sql("SELECT valor FROM configuracao WHERE chave = 'chave_interna'"))[0] || {}).valor;
    try {
      await mitra.functions.executeAsync(f.id, { acao: 'lab_aplicar', lab_id: labId, pedido_id: linha[0].pedido_id, chave_interna: chave });
    } catch (erro) {
      await dml(`UPDATE banner_lab SET situacao = 'pronto' WHERE id = CAST(:l AS INTEGER) AND situacao = 'aplicando'`, { l: labId });
      return { ok: false, erro: 'PIPELINE_AUSENTE', mensagem: String(erro && erro.message || erro) };
    }
    return { ok: true, situacao: 'aplicando' };
  }

  return { ok: false, erro: 'ACAO_INVALIDA', acao };
};

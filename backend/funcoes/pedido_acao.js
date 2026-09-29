// Dispara uma acao da pipeline para um pedido existente, em segundo plano.
// Acoes aceitas: criar (com simular opcional), banner (dispensar | aplicar | regerar), extrair (refazer),
// trocar_logo (logo enviada em partes por logo_parte).
const { createClient } = require('@mitralab.io/functions-sdk');

const PERMITIDAS = {
  criar: ['curadoria'],
  extrair: ['falhou', 'precisa_catalogo', 'aguardando_anexo', 'curadoria'],
  banner: ['curadoria', 'concluido'],
  trocar_logo: ['curadoria', 'concluido'],
  telufia: ['concluido'],
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
  const MARCA_EXPIRA_MS = 20 * 60 * 1000;
  const marcaViva = pedido.execucao_atual && pedido.execucao_desde
    && Date.now() - new Date(pedido.execucao_desde).getTime() < MARCA_EXPIRA_MS;
  if (marcaViva) return { ok: false, erro: 'EM_EXECUCAO', desde: pedido.execucao_desde };

  if (acao === 'extrair' && pedido.portal_id) return { ok: false, erro: 'STATUS_NAO_PERMITE', status: 'concluido', acao };
  const entrada = { acao, pedido_id: pedidoId };
  if (acao === 'extrair' && (ev.site !== undefined || ev.observacao !== undefined || ev.sem_anexo)) {
    let novoSite = String(ev.site || '').trim();
    if (novoSite && !/^https?:\/\//i.test(novoSite)) novoSite = `https://${novoSite}`;
    if (novoSite) { try { new URL(novoSite); } catch (e) { return { ok: false, erro: 'SITE_INVALIDO', site: ev.site }; } }
    await mitra.sql.executeDml([{ sql: `UPDATE pedidos SET
        site = CASE WHEN CAST(:ts AS BOOLEAN) THEN NULLIF(:s, '') ELSE site END,
        foco = CASE WHEN CAST(:to AS BOOLEAN) THEN NULLIF(:o, '') ELSE foco END,
        anexo_nome = CASE WHEN CAST(:sa AS BOOLEAN) THEN NULL ELSE anexo_nome END,
        atualizado_em = now() WHERE pedido_id = :p`,
    parameters: { p: pedidoId, s: novoSite, ts: String(ev.site !== undefined), o: String(ev.observacao || '').trim().slice(0, 500),
      to: String(ev.observacao !== undefined), sa: String(!!ev.sem_anexo && !ev.anexo_nome) } }]);
    await mitra.sql.executeDml([{ sql: `INSERT INTO pedido_eventos (pedido_id, etapa, mensagem) VALUES (:p, 'pedido', :m)`,
      parameters: { p: pedidoId, m: `busca refeita pelo usuário${novoSite ? ` · site: ${novoSite}` : ''}${ev.anexo_nome ? ` · anexo: ${ev.anexo_nome}` : ''}${ev.observacao ? ` · observação: ${String(ev.observacao).slice(0, 200)}` : ''}` } }]);
  }
  if (acao === 'extrair' && ev.anexo_nome) {
    const total = Math.max(0, parseInt(ev.anexo_partes, 10) || 0);
    await mitra.sql.executeDml([{ sql: `DELETE FROM pedido_arquivos WHERE pedido_id = :p AND tipo = 'anexo'
      AND parte >= CAST(:q AS INTEGER)`, parameters: { p: pedidoId, q: String(total) } }]);
    const partes = await sql(`SELECT count(*) AS n FROM pedido_arquivos WHERE pedido_id = :p AND tipo = 'anexo'`, { p: pedidoId });
    if (!total || Number(partes[0].n) !== total) {
      return { ok: false, erro: 'ANEXO_AUSENTE', mensagem: `O arquivo chegou incompleto (${partes[0].n} de ${total} partes); envie de novo.` };
    }
    await mitra.sql.executeDml([{ sql: `UPDATE pedidos SET anexo_nome = :n, anexo_partes = CAST(:q AS INTEGER),
      atualizado_em = now() WHERE pedido_id = :p`, parameters: { p: pedidoId, n: String(ev.anexo_nome).slice(0, 200), q: String(partes[0].n) } }]);
  }
  if (acao === 'criar') entrada.simular = !!ev.simular;
  if (acao === 'banner') {
    entrada.acao_banner = ev.acao_banner;
    for (const k of ['escolhas', 'pecas', 'feedback', 'cor']) if (ev[k] !== undefined) entrada[k] = ev[k];
  }
  if (acao === 'trocar_logo') {
    await mitra.sql.executeDml([{ sql: `DELETE FROM pedido_arquivos WHERE pedido_id = :p AND tipo = 'logo_envio'
      AND parte >= CAST(:q AS INTEGER)`, parameters: { p: pedidoId, q: String(Math.max(0, parseInt(ev.logo_partes, 10) || 0)) } }]);
    const partes = await sql(`SELECT count(*) AS n FROM pedido_arquivos WHERE pedido_id = :p AND tipo = 'logo_envio'`, { p: pedidoId });
    const total = Math.max(0, parseInt(ev.logo_partes, 10) || 0);
    const nome = String(ev.logo_nome || '').trim();
    if (!nome || !/\.(png|jpe?g|svg|webp)$/i.test(nome)) return { ok: false, erro: 'LOGO_FORMATO', mensagem: 'Envie a logo em PNG, JPG, SVG ou WEBP.' };
    if (!total || Number(partes[0].n) !== total) {
      return { ok: false, erro: 'ANEXO_AUSENTE', mensagem: `A logo chegou incompleta (${partes[0].n} de ${total} partes); envie de novo.` };
    }
    await mitra.sql.executeDml([
      { sql: `DELETE FROM pedido_arquivos WHERE pedido_id = :p AND tipo = 'logo_envio_nome'`, parameters: { p: pedidoId } },
      { sql: `INSERT INTO pedido_arquivos (pedido_id, tipo, parte, conteudo_base64) VALUES (:p, 'logo_envio_nome', 0, :n)`,
        parameters: { p: pedidoId, n: nome.slice(0, 200) } },
    ]);
  }
  await mitra.sql.executeDml([{ sql: 'UPDATE pedidos SET acao_desde = now() WHERE pedido_id = :p', parameters: { p: pedidoId } }]);
  const lista = await mitra.functionsAdmin.list({ size: 100 });
  const pipeline = (lista.content || lista.items || []).find((f) => f.name === 'pipeline_poc');
  if (!pipeline) return { ok: false, erro: 'PIPELINE_AUSENTE' };
  const criarDeVerdade = acao === 'criar' && !entrada.simular;
  if (criarDeVerdade) {
    const tomado = await sql(`UPDATE pedidos SET status = 'criando', criacao_inicio = now(),
        curadoria_fim = COALESCE(curadoria_fim, now()), atualizado_em = now()
      WHERE pedido_id = :p AND status = 'curadoria' AND portal_id IS NULL RETURNING pedido_id`, { p: pedidoId });
    if (!tomado.length) return { ok: false, erro: 'STATUS_NAO_PERMITE', status: 'criando', acao };
  }
  if (acao === 'banner' && ev.acao_banner === 'regerar') {
    const tomado = await sql(`UPDATE pedidos SET banners_situacao = 'regerando', acao_desde = now(), atualizado_em = now()
      WHERE pedido_id = :p AND COALESCE(banners_situacao, '') NOT IN ('gerando', 'regerando', 'aplicando') RETURNING pedido_id`, { p: pedidoId });
    if (!tomado.length) return { ok: false, erro: 'EM_EXECUCAO', mensagem: 'Os banners novos já estão sendo criados.' };
  }
  if (acao === 'extrair') {
    const tomado = await sql(`UPDATE pedidos SET status = 'extraindo', erro = NULL, erro_codigo = NULL, atualizado_em = now()
      WHERE pedido_id = :p AND portal_id IS NULL AND status IN ('falhou', 'precisa_catalogo', 'aguardando_anexo', 'curadoria') RETURNING pedido_id`, { p: pedidoId });
    if (!tomado.length) return { ok: false, erro: 'STATUS_NAO_PERMITE', status: 'extraindo', acao };
  }
  let execucao;
  try {
    execucao = await mitra.functions.executeAsync(pipeline.id, entrada);
  } catch (erro) {
    if (criarDeVerdade) {
      await mitra.sql.executeDml([{ sql: `UPDATE pedidos SET status = 'curadoria', criacao_inicio = NULL
        WHERE pedido_id = :p AND status = 'criando' AND portal_id IS NULL`, parameters: { p: pedidoId } }]);
    }
    if (acao === 'banner' && ev.acao_banner === 'regerar') {
      await mitra.sql.executeDml([{ sql: `UPDATE pedidos SET banners_situacao = 'prontos' WHERE pedido_id = :p AND banners_situacao = 'regerando'`,
        parameters: { p: pedidoId } }]);
    }
    if (acao === 'extrair') {
      await mitra.sql.executeDml([{ sql: `UPDATE pedidos SET status = :s WHERE pedido_id = :p AND status = 'extraindo'`,
        parameters: { p: pedidoId, s: pedido.status } }]);
    }
    return { ok: false, erro: 'PIPELINE_AUSENTE', mensagem: String(erro && erro.message || erro) };
  }
  return { ok: true, pedido_id: pedidoId, acao, execucao: execucao.id };
};

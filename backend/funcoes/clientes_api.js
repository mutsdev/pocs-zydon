// API de leitura para o agente de preparação de reunião.
// POST {"nome": "..."} (ou {"pedido_id": "..."}) com o token dxt_... no header x-api-key.
// Devolve cliente, produtos, prompt da IA do portal, perguntas para a reunião e a situação do portal.
const { createClient } = require('@mitralab.io/functions-sdk');
const crypto = require('crypto');

async function comEspera(fazer) {
  for (let tentativa = 0; ; tentativa += 1) {
    try {
      return await fazer();
    } catch (erro) {
      if (!(erro && erro.status === 429) || tentativa >= 5) throw erro;
      await new Promise((ok) => setTimeout(ok, 1500 * (tentativa + 1)));
    }
  }
}

function lerCorpo(event) {
  let corpo = event && event.input !== undefined ? event.input : event;
  if (corpo && typeof corpo.body === 'string') corpo = corpo.body;
  if (typeof corpo === 'string') {
    try { corpo = JSON.parse(corpo); } catch (e) { return null; }
  }
  return corpo && typeof corpo === 'object' ? corpo : null;
}

function semAcento(texto) {
  return String(texto || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function limpar(texto, limite) {
  const t = String(texto || '').replace(/\s+/g, ' ').trim();
  if (!limite || t.length <= limite) return t;
  const corte = t.slice(0, limite);
  const ponto = Math.max(corte.lastIndexOf('. '), corte.lastIndexOf('! '));
  return ponto > limite * 0.5 ? corte.slice(0, ponto + 1) : `${corte.replace(/\s+\S*$/, '')}…`;
}

function json(valor) {
  if (valor === null || valor === undefined) return null;
  if (typeof valor === 'object' && valor.value !== undefined && valor.type) valor = valor.value;
  if (typeof valor === 'string') {
    try { return JSON.parse(valor); } catch (e) { return null; }
  }
  return valor;
}

function produtosDoCatalogo(catalogo) {
  const etapas = Object.fromEntries(((catalogo && catalogo.etapas) || []).map((e) => [e.endpoint, e]));
  const categorias = {};
  for (const r of ((etapas.categories || {}).requests || [])) {
    if (r.salvar_id_como && r.payload) categorias[`{{${r.salvar_id_como}}}`] = r.payload.name;
  }
  return ((etapas.products || {}).requests || []).map((r) => r.payload || {}).filter((p) => p.name).map((p) => ({
    nome: limpar(p.name),
    categoria: categorias[p.category_id] || null,
    descricao: limpar(p.description, 220) || null,
  }));
}

const NORMALIZAR = "translate(lower(p.cliente), 'áàâãäéèêëíìîïóòôõöúùûüçñ', 'aaaaaeeeeiiiiooooouuuucn')";

module.exports = async (event, context) => {
  const corpo = lerCorpo(event);
  if (!corpo) return { ok: false, erro: 'JSON_INVALIDO', mensagem: 'Envie um corpo JSON, por exemplo {"nome": "acqua"}.' };
  const cabecalhos = (context && context.request && context.request.headers) || {};
  const token = String(cabecalhos['x-api-key'] || '').trim();
  if (!token) return { ok: false, erro: 'TOKEN_AUSENTE', mensagem: 'Envie o token no header x-api-key.' };

  const mitra = createClient();
  await mitra.init();
  const sql = async (q, p = {}) => ((await comEspera(() => mitra.sql.executeQuery(q, p))).rows || []);

  const hash = crypto.createHash('sha256').update(token).digest('hex');
  const dono = (await sql(`SELECT t.id AS token_id, e.id, e.nome, e.cargo,
      lower(e.email) = (SELECT valor FROM configuracao WHERE chave = 'admin_email') AS admin
    FROM tokens_api t JOIN executivos e ON e.id = t.executivo_id AND e.ativo
    WHERE t.token_hash = :h AND t.revogado_em IS NULL`, { h: hash }))[0];
  if (!dono) return { ok: false, erro: 'TOKEN_INVALIDO', mensagem: 'Token inválido, revogado ou de usuário desativado.' };
  try {
    await comEspera(() => mitra.sql.executeDml([{ sql: 'UPDATE tokens_api SET ultimo_uso = now() WHERE id = CAST(:i AS INTEGER)', parameters: { i: String(dono.token_id) } }]));
  } catch (e) { /* uso do token é só informativo */ }

  const todos = dono.admin === true || dono.admin === 't' || dono.cargo === 'Agente de prospecção';
  const escopo = { e: todos ? '' : String(dono.id) };
  const pedidoId = String(corpo.pedido_id || '').trim();
  const nome = semAcento(corpo.nome);
  if (!pedidoId && nome.length < 2) {
    return { ok: false, erro: 'CAMPOS_FALTANDO', mensagem: 'Envie "nome" com pelo menos 2 letras (ou "pedido_id").' };
  }

  const porPagina = Math.min(Math.max(parseInt(corpo.por_pagina, 10) || 20, 1), 50);
  const pagina = Math.max(parseInt(corpo.pagina, 10) || 1, 1);
  const base = `FROM pedidos p WHERE p.catalogo IS NOT NULL AND p.status IN ('concluido', 'criando', 'curadoria')
    AND (:e = '' OR p.executivo_id = CAST(NULLIF(:e, '') AS INTEGER))`;
  const achados = pedidoId
    ? await sql(`SELECT p.pedido_id, p.cliente, p.segmento, p.site, p.portal_url, p.loja_aberta, p.criado_em ${base}
        AND p.pedido_id = :pid`, { ...escopo, pid: pedidoId })
    : await sql(`SELECT p.pedido_id, p.cliente, p.segmento, p.site, p.portal_url, p.loja_aberta, p.criado_em ${base}
        AND ${NORMALIZAR} LIKE '%' || :n || '%' ORDER BY p.criado_em DESC
        LIMIT CAST(:lim AS INTEGER) OFFSET CAST(:off AS INTEGER)`, { ...escopo, n: nome, lim: String(porPagina), off: String((pagina - 1) * porPagina) });

  const situacao = (l) => (!l.portal_url ? null : (l.loja_aberta === true || l.loja_aberta === 't') ? 'liberado' : 'criado');
  const total = pedidoId ? achados.length : Number(((await sql(`SELECT count(*) AS n ${base}
      AND ${NORMALIZAR} LIKE '%' || :n || '%'`, { ...escopo, n: nome }))[0] || {}).n || 0);
  if (!achados.length) {
    return { ok: false, erro: 'NAO_ENCONTRADO', mensagem: `Nenhum cliente gerado com "${corpo.nome || pedidoId}".` };
  }
  if (total > 1) {
    return {
      ok: true, multiplos: true, total, pagina, por_pagina: porPagina,
      tem_mais: pagina * porPagina < total,
      mensagem: 'Mais de um resultado. Repita a chamada com o "pedido_id" escolhido.',
      resultados: achados.map((l) => ({ pedido_id: l.pedido_id, cliente: l.cliente, segmento: l.segmento || null,
        site: l.site || null, status: situacao(l), link: l.portal_url || null, gerado_em: l.criado_em })),
    };
  }

  const p = (await sql(`SELECT p.pedido_id, p.cliente, p.segmento, p.site, p.portal_url, p.loja_aberta, p.portal_lido_em,
      CAST(p.catalogo AS TEXT) AS catalogo, p.prompt_ia, CAST(p.perguntas_ia AS TEXT) AS perguntas_ia, p.criado_em
    FROM pedidos p WHERE p.pedido_id = :pid`, { pid: achados[0].pedido_id }))[0];
  const status = situacao(p);
  const avisos = [];
  if (!status) avisos.push('Portal ainda não criado.');
  else if (status === 'criado') avisos.push('Portal criado, mas ainda não liberado para visitantes.');
  if (!p.prompt_ia) avisos.push('Prompt da IA do portal ainda não disponível para este cliente.');
  const perguntas = json(p.perguntas_ia);
  if (!Array.isArray(perguntas) || !perguntas.length) avisos.push('Perguntas para a reunião ainda não geradas para este cliente.');

  return {
    ok: true,
    pedido_id: p.pedido_id,
    cliente: { nome: p.cliente, segmento: p.segmento || null, site: p.site || null },
    status,
    link: p.portal_url || null,
    aviso: avisos.length ? avisos.join(' ') : null,
    produtos: produtosDoCatalogo(json(p.catalogo)),
    prompt_ia: p.prompt_ia || null,
    perguntas_ia: Array.isArray(perguntas) ? perguntas : [],
    gerado_em: p.criado_em,
    portal_conferido_em: p.portal_lido_em || null,
  };
};

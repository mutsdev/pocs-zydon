// Nucleo do Dexter (embutido por publicar_funcao.mjs no lugar de __DEXTER__):
// valida as empresas, abre um lote de pedidos automaticos (sem curadoria) e acorda o despacho.
const COMMIT_DEXTER = '7b3d073427e47ecf660280920bfba23c3178834a';
const MAX_EMPRESAS = 50;

function lerEmpresa(bruta, indice) {
  const t = (v) => (v === undefined || v === null ? '' : String(v)).trim();
  const b = bruta || {};
  const empresa = t(b.empresa || b.cliente).slice(0, 200);
  const referencia = t(b.referencia).slice(0, 100);
  const observacao = t(b.observacao).slice(0, 500);
  const variacoes = b.variacoes === true || b.variacoes === 'sim' || b.variacoes === 'true';
  let site = t(b.site);
  const faltando = [];
  if (!empresa) faltando.push('empresa');
  if (!site) faltando.push('site');
  if (faltando.length) return { indice, referencia, empresa, erro: 'CAMPOS_FALTANDO', faltando };
  if (!/^https?:\/\//i.test(site)) site = `https://${site}`;
  try {
    const u = new URL(site);
    if (!u.hostname.includes('.')) throw new Error('host');
  } catch (e) {
    return { indice, referencia, empresa, erro: 'SITE_INVALIDO', site: t(b.site) };
  }
  return { indice, empresa, site, referencia, observacao, variacoes };
}

async function chaveInternaDexter(mitra) {
  const r = await mitra.sql.executeQuery("SELECT valor FROM configuracao WHERE chave = 'chave_interna'", {});
  return ((r.rows || [])[0] || {}).valor || null;
}

async function acordarDespacho(mitra) {
  try {
    const chave = await chaveInternaDexter(mitra);
    const lista = await mitra.functionsAdmin.list({ size: 100 });
    const pipeline = (lista.content || lista.items || []).find((f) => f.name === 'pipeline_poc');
    if (!pipeline || !chave) return false;
    await mitra.functions.executeAsync(pipeline.id, { acao: 'despachar', chave_interna: chave });
    return true;
  } catch (e) {
    return false;
  }
}

async function abrirLote(mitra, dono, empresas, opcoes = {}) {
  const sql = async (q, p = {}) => (await mitra.sql.executeQuery(q, p)).rows || [];
  const dml = (q, p = {}) => mitra.sql.executeDml([{ sql: q, parameters: p }]);
  if (!Array.isArray(empresas) || !empresas.length) return { ok: false, erro: 'CAMPOS_FALTANDO', faltando: ['empresas'] };
  if (empresas.length > MAX_EMPRESAS) return { ok: false, erro: 'LOTE_GRANDE', mensagem: `Envie no máximo ${MAX_EMPRESAS} empresas por vez.` };
  const lidas = empresas.map(lerEmpresa);
  const erros = lidas.filter((l) => l.erro);
  const vistas = new Set();
  const validas = [];
  for (const l of lidas.filter((x) => !x.erro)) {
    const chave = l.referencia ? `r:${l.referencia}` : `s:${new URL(l.site).hostname.replace(/^www\./, '')}`;
    if (vistas.has(chave)) { erros.push({ indice: l.indice, referencia: l.referencia, empresa: l.empresa, erro: 'REPETIDA_NO_LOTE' }); continue; }
    vistas.add(chave);
    validas.push(l);
  }
  if (!validas.length) return { ok: false, erro: 'NENHUMA_VALIDA', erros };

  const nome = String(opcoes.nome || '').trim().slice(0, 120)
    || `Lote ${new Date().toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' })}`;
  const lote = await sql(`INSERT INTO lotes (nome, executivo_id, origem) VALUES (:n, CAST(:e AS INTEGER), :o) RETURNING id`,
    { n: nome, e: String(dono.id), o: opcoes.origem || 'api' });
  const loteId = lote[0].id;
  const itens = [];
  for (const l of validas) {
    if (l.referencia) {
      const ja = await sql(`SELECT pedido_id, status, portal_url FROM pedidos
        WHERE executivo_id = CAST(:e AS INTEGER) AND referencia_externa = :r ORDER BY id DESC LIMIT 1`,
      { e: String(dono.id), r: l.referencia });
      if (ja.length) {
        itens.push({ indice: l.indice, referencia: l.referencia, empresa: l.empresa, pedido_id: ja[0].pedido_id,
          status: ja[0].status, url: ja[0].portal_url || null, duplicado: true });
        continue;
      }
    }
    const numero = await sql(`INSERT INTO contador_pedidos (dia, ultimo) VALUES (CAST(now() AS DATE), 1)
      ON CONFLICT (dia) DO UPDATE SET ultimo = contador_pedidos.ultimo + 1 RETURNING ultimo, to_char(dia, 'YYYY-MM-DD') AS dia`);
    const pedidoId = `poc-${numero[0].dia}-${String(numero[0].ultimo).padStart(3, '0')}`;
    await dml(`INSERT INTO pedidos (pedido_id, executivo_id, cliente, site, status, commit_codigo, foco, variacoes,
        automatico, lote_id, referencia_externa)
      VALUES (:p, CAST(:e AS INTEGER), :c, :s, 'na_fila', :cm, NULLIF(:fo, ''), CAST(:va AS BOOLEAN), true,
        CAST(:l AS INTEGER), NULLIF(:r, '')) ON CONFLICT (pedido_id) DO NOTHING`,
    { p: pedidoId, e: String(dono.id), c: l.empresa, s: l.site, cm: COMMIT_DEXTER, fo: l.observacao,
      va: l.variacoes ? 'true' : 'false', l: String(loteId), r: l.referencia });
    await dml(`INSERT INTO pedido_eventos (pedido_id, etapa, mensagem) VALUES (:p, 'dexter', :m)`,
      { p: pedidoId, m: `na fila do ${nome} (${opcoes.origem === 'tela' ? 'pela tela' : 'pela API'}) · sem curadoria`
        + (l.observacao ? ` · observação: ${l.observacao}` : '') + (l.variacoes ? ' · com variações' : '') });
    itens.push({ indice: l.indice, referencia: l.referencia || null, empresa: l.empresa, pedido_id: pedidoId, status: 'na_fila' });
  }
  if (!itens.some((i) => !i.duplicado)) {
    await dml('DELETE FROM lotes WHERE id = CAST(:l AS INTEGER)', { l: String(loteId) });
    return { ok: true, lote_id: null, itens, erros, aviso: 'todas as empresas já tinham pedido com a mesma referência' };
  }
  const acordado = await acordarDespacho(mitra);
  return { ok: true, lote_id: loteId, nome, itens, erros, ...(acordado ? {} : { aviso: 'a fila começa em até 10 minutos' }) };
}

const SITUACAO_PUBLICA = {
  na_fila: 'na_fila', extraindo: 'buscando', curadoria: 'buscando', aguardando_anexo: 'buscando',
  criando: 'criando', concluido: 'concluido', falhou: 'falhou', precisa_catalogo: 'falhou',
};

async function andamentoDexter(mitra, executivoId, corpo) {
  const sql = async (q, p = {}) => (await mitra.sql.executeQuery(q, p)).rows || [];
  const colunas = `pedido_id, cliente AS empresa, site, referencia_externa AS referencia, lote_id, status,
    portal_url AS url, produtos, COALESCE(motivo_catalogo, erro) AS motivo, criado_em, concluido_em`;
  const p = { e: String(executivoId) };
  let linhas;
  if (corpo.pedido_id) {
    linhas = await sql(`SELECT ${colunas} FROM pedidos WHERE executivo_id = CAST(:e AS INTEGER) AND pedido_id = :p`, { ...p, p: String(corpo.pedido_id) });
  } else if (corpo.referencia) {
    linhas = await sql(`SELECT ${colunas} FROM pedidos WHERE executivo_id = CAST(:e AS INTEGER) AND referencia_externa = :r ORDER BY id DESC LIMIT 1`, { ...p, r: String(corpo.referencia) });
  } else if (corpo.lote_id) {
    linhas = await sql(`SELECT ${colunas} FROM pedidos WHERE executivo_id = CAST(:e AS INTEGER) AND lote_id = CAST(:l AS INTEGER) ORDER BY id LIMIT 200`, { ...p, l: String(parseInt(corpo.lote_id, 10) || 0) });
  } else {
    return { ok: false, erro: 'CAMPOS_FALTANDO', faltando: ['pedido_id, referencia ou lote_id'] };
  }
  const itens = linhas.map((l) => ({ ...l, situacao: SITUACAO_PUBLICA[l.status] || l.status,
    motivo: ['falhou', 'precisa_catalogo'].includes(l.status) ? l.motivo : null }));
  if (corpo.lote_id) {
    const conta = (s) => itens.filter((i) => i.situacao === s).length;
    return { ok: true, lote_id: Number(corpo.lote_id), total: itens.length, na_fila: conta('na_fila'), buscando: conta('buscando'),
      criando: conta('criando'), concluidos: conta('concluido'), falharam: conta('falhou'), itens };
  }
  if (!itens.length) return { ok: false, erro: 'PEDIDO_DESCONHECIDO' };
  return { ok: true, ...itens[0] };
}

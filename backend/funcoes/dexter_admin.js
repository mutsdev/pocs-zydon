// Admin do Dexter: lote pela tela, tokens de API (gerar/revogar) e controle da fila (retentar/cancelar).
const { createClient } = require('@mitralab.io/functions-sdk');
const crypto = require('crypto');

__GUARDA__
__DEXTER__

const PROBLEMAS = {
  produtos_errados: 'produtos que não são do cliente',
  imagens_ruins: 'imagens erradas ou ruins',
  poucos_produtos: 'poucos produtos',
  fora_do_foco: 'produtos fora do foco',
  nomes_ruins: 'nomes ruins ou cortados',
  precos_estranhos: 'preços estranhos',
  categorias_ruins: 'categorias ruins',
  banner_ruim: 'banner ruim',
  logo_errada: 'logo errada',
  segmento_errado: 'segmento errado',
};


function lerXlsx(buf) {
  const zlib = require('zlib');
  let fimDir = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 70000); i -= 1) { if (buf.readUInt32LE(i) === 0x06054b50) { fimDir = i; break; } }
  if (fimDir < 0) throw new Error('não é xlsx');
  const total = buf.readUInt16LE(fimDir + 10);
  let p = buf.readUInt32LE(fimDir + 16);
  const arquivos = {};
  for (let k = 0; k < total; k += 1) {
    if (buf.readUInt32LE(p) !== 0x02014b50) break;
    const metodo = buf.readUInt16LE(p + 10); const tam = buf.readUInt32LE(p + 20);
    const nl = buf.readUInt16LE(p + 28); const el = buf.readUInt16LE(p + 30); const cl = buf.readUInt16LE(p + 32);
    const local = buf.readUInt32LE(p + 42); const nome = buf.slice(p + 46, p + 46 + nl).toString('utf-8');
    arquivos[nome] = { metodo, tam, local };
    p += 46 + nl + el + cl;
  }
  const ler = (nome) => {
    const a = arquivos[nome]; if (!a) return '';
    const ini = a.local + 30 + buf.readUInt16LE(a.local + 26) + buf.readUInt16LE(a.local + 28);
    const dados = buf.slice(ini, ini + a.tam);
    return (a.metodo === 8 ? zlib.inflateRawSync(dados) : dados).toString('utf-8');
  };
  const ent = (t) => t.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n))).replace(/&amp;/g, '&');
  const textos = (x) => ent((x.match(/<t[^>]*>[\s\S]*?<\/t>/g) || []).map((t) => t.replace(/<[^>]+>/g, '')).join(''));
  const comuns = (ler('xl/sharedStrings.xml').match(/<si>[\s\S]*?<\/si>/g) || []).map(textos);
  const folhaNome = Object.keys(arquivos).filter((n) => /^xl\/worksheets\/sheet\d+\.xml$/.test(n))
    .sort((a, b) => parseInt(a.match(/\d+/)[0], 10) - parseInt(b.match(/\d+/)[0], 10))[0];
  if (!folhaNome) throw new Error('sem planilha');
  const tabela = [];
  for (const linha of ler(folhaNome).match(/<row[\s\S]*?<\/row>/g) || []) {
    const cels = [];
    for (const c of linha.match(/<c\b[^>]*?(?:\/>|>[\s\S]*?<\/c>)/g) || []) {
      const ref = (c.match(/\br="([A-Z]+)\d+"/) || [])[1] || '';
      const col = ref ? ref.split('').reduce((acc, l) => acc * 26 + l.charCodeAt(0) - 64, 0) - 1 : cels.length;
      const tipo = (c.match(/\bt="([^"]+)"/) || [])[1];
      const v = (c.match(/<v>([\s\S]*?)<\/v>/) || [])[1];
      cels[col] = tipo === 's' ? (comuns[Number(v)] || '') : tipo === 'inlineStr' ? textos(c) : ent(v || '');
    }
    tabela.push(Array.from(cels, (x) => x || ''));
  }
  return tabela;
}

module.exports = async (event, context) => {
  const ev = (event && event.input) ? event.input : (event || {});
  const mitra = createClient();
  await mitra.init();
  const g = await guarda(mitra, context);
  if (!g.ok) return g;
  const agente = !g.sessao.admin && g.sessao.cargo === 'Agente de prospecção' && !!g.sessao.executivo_id;
  if (!g.sessao.admin && !agente) return { ok: false, erro: 'SO_ADMIN', mensagem: 'Só o administrador e o Dexter controlam esta tela.' };
  const meu = agente ? String(g.sessao.executivo_id) : '';
  const sql = async (q, p = {}) => (await mitra.sql.executeQuery(q, p)).rows || [];
  const dml = (q, p = {}) => mitra.sql.executeDml([{ sql: q, parameters: p }]);
  const acao = String(ev.acao || '');

  if (acao === 'ler_planilha') {
    const nomeArquivo = String(ev.nome_arquivo || '');
    if (!/\.(xlsx|csv)$/i.test(nomeArquivo)) return { ok: false, erro: 'PLANILHA_FORMATO' };
    const b64 = String(ev.conteudo_base64 || '');
    if (!b64) return { ok: false, erro: 'CAMPOS_FALTANDO', faltando: ['conteudo_base64'] };
    if (b64.length > 3000000) return { ok: false, erro: 'PLANILHA_GRANDE' };
    let tabela;
    const bruto = Buffer.from(b64, 'base64');
    try {
      if (/\.csv$/i.test(nomeArquivo)) {
        const texto = bruto.toString('utf-8').replace(/^\uFEFF/, '');
        const primeira = texto.split(/\r?\n/)[0] || '';
        const sep = [';', '\t', ','].sort((a, b) => primeira.split(b).length - primeira.split(a).length)[0];
        tabela = texto.split(/\r?\n/).map((l) => l.split(sep).map((c) => c.replace(/^"|"$/g, '')));
      } else {
        tabela = lerXlsx(bruto);
      }
    } catch (e) {
      return { ok: false, erro: 'PLANILHA_ILEGIVEL', detalhe: String(e && e.message || e).slice(0, 300) };
    }
    const limpar = (v) => String(v === undefined || v === null ? '' : v).trim();
    const normal = (v) => limpar(v).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const linhas = (tabela || []).map((l) => (Array.isArray(l) ? l.map(limpar) : [])).filter((l) => l.some(Boolean));
    if (!linhas.length) return { ok: false, erro: 'PLANILHA_VAZIA' };
    const achar = (cab, termos) => cab.findIndex((c) => termos.some((t) => c === t || c.startsWith(t)));
    const cab = linhas[0].map(normal);
    let col = {
      empresa: achar(cab, ['empresa', 'cliente', 'nome', 'razao', 'fantasia']),
      site: achar(cab, ['site', 'url', 'endereco', 'dominio', 'link', 'www']),
      observacao: achar(cab, ['observ', 'obs', 'foco', 'nota']),
      referencia: achar(cab, ['referencia', 'ref', 'id', 'codigo']),
    };
    let corpo = linhas.slice(1);
    if (col.empresa < 0 || col.site < 0) {
      col = { empresa: 0, site: 1, observacao: 2, referencia: -1 };
      corpo = linhas;
    }
    const pegar = (l, i) => (i >= 0 ? limpar(l[i]) : '');
    const empresas = corpo.map((l) => ({ empresa: pegar(l, col.empresa), site: pegar(l, col.site),
      observacao: pegar(l, col.observacao), referencia: pegar(l, col.referencia) }))
      .filter((e) => e.empresa || e.site);
    return { ok: true, empresas, total: empresas.length, com_cabecalho: corpo !== linhas };
  }

  if (acao === 'lote') {
    const alvo = agente ? meu : (ev.executivo_id ? String(ev.executivo_id) : '');
    const dono = (await sql(`SELECT id, nome FROM executivos WHERE ativo AND
      (CASE WHEN :e = '' THEN cargo = 'Agente de prospecção' ELSE id = CAST(NULLIF(:e, '') AS INTEGER) END) ORDER BY id LIMIT 1`, { e: alvo }))[0];
    if (!dono) return { ok: false, erro: 'EXECUTIVO_DESCONHECIDO' };
    return abrirLote(mitra, dono, ev.empresas, { nome: ev.nome, origem: 'tela' });
  }

  if (acao === 'gerar_token') {
    const dono = (await sql('SELECT id, nome FROM executivos WHERE id = CAST(:e AS INTEGER) AND ativo', { e: agente ? meu : String(ev.executivo_id || 0) }))[0];
    if (!dono) return { ok: false, erro: 'EXECUTIVO_DESCONHECIDO' };
    const token = `dxt_${crypto.randomBytes(24).toString('base64url')}`;
    const hash = crypto.createHash('sha256').update(token).digest('hex');
    const linha = await sql(`INSERT INTO tokens_api (executivo_id, token_hash, prefixo) VALUES (CAST(:e AS INTEGER), :h, :p)
      RETURNING id, prefixo, criado_em`, { e: String(dono.id), h: hash, p: token.slice(0, 10) });
    return { ok: true, token, id: linha[0].id, prefixo: linha[0].prefixo, criado_em: linha[0].criado_em, usuario: dono.nome };
  }

  if (acao === 'revogar_token') {
    const r = await sql(`UPDATE tokens_api SET revogado_em = now() WHERE id = CAST(:i AS INTEGER) AND revogado_em IS NULL
      AND (:m = '' OR executivo_id = CAST(NULLIF(:m, '') AS INTEGER)) RETURNING id, revogado_em`,
      { i: String(ev.id || 0), m: meu });
    return r.length ? { ok: true, ...r[0] } : { ok: false, erro: 'TOKEN_DESCONHECIDO' };
  }

  if (acao === 'retentar' || acao === 'cancelar') {
    const pedidoId = String(ev.pedido_id || '').trim();
    const r = acao === 'retentar'
      ? await sql(`UPDATE pedidos SET status = 'na_fila', erro = NULL, erro_codigo = NULL, motivo_catalogo = NULL,
          execucao_atual = NULL, falhou_em = NULL, concluido_em = NULL, saiu_fila_em = NULL, atualizado_em = now()
        WHERE pedido_id = :p AND automatico AND (:m = '' OR executivo_id = CAST(NULLIF(:m, '') AS INTEGER)) AND portal_id IS NULL AND status IN ('falhou', 'precisa_catalogo') RETURNING pedido_id, status`, { p: pedidoId, m: meu })
      : await sql(`UPDATE pedidos SET status = 'falhou', erro = :motivo, erro_codigo = 'CANCELADO',
          falhou_em = now(), atualizado_em = now()
        WHERE pedido_id = :p AND automatico AND (:m = '' OR executivo_id = CAST(NULLIF(:m, '') AS INTEGER)) AND status = 'na_fila' RETURNING pedido_id, status`, { p: pedidoId, m: meu, motivo: agente ? 'cancelado pelo Dexter' : 'cancelado pelo administrador' });
    if (!r.length) return { ok: false, erro: 'STATUS_NAO_PERMITE', acao };
    await dml(`INSERT INTO pedido_eventos (pedido_id, etapa, mensagem) VALUES (:p, 'dexter', :m)`,
      { p: pedidoId, m: acao === 'retentar' ? (agente ? 'de volta para a fila pelo Dexter' : 'de volta para a fila pelo administrador') : (agente ? 'cancelado pelo Dexter' : 'cancelado pelo administrador') });
    if (acao === 'retentar') await acordarDespacho(mitra);
    return { ok: true, ...r[0] };
  }

  if (acao === 'avaliar') {
    const pedidoId = String(ev.pedido_id || '').trim();
    const nota = Number(ev.nota);
    if (!pedidoId || !Number.isInteger(nota) || nota < 1 || nota > 5) return { ok: false, erro: 'CAMPOS_FALTANDO', faltando: ['nota'] };
    const validos = Object.keys(PROBLEMAS);
    const problemas = (Array.isArray(ev.problemas) ? ev.problemas : []).map(String).filter((x) => validos.includes(x));
    const comentario = String(ev.comentario || '').trim().slice(0, 1000);
    const alvo = (await sql(`SELECT pedido_id, executivo_id, segmento FROM pedidos WHERE pedido_id = :p AND automatico
      AND (:m = '' OR executivo_id = CAST(NULLIF(:m, '') AS INTEGER))`, { p: pedidoId, m: meu }))[0];
    if (!alvo) return { ok: false, erro: 'PEDIDO_DESCONHECIDO' };
    const r = await sql(`INSERT INTO avaliacoes_portal (pedido_id, executivo_id, nota, problemas, comentario, segmento)
      VALUES (:p, CAST(:e AS INTEGER), CAST(:n AS INTEGER), :pr, NULLIF(:c, ''), :s)
      ON CONFLICT (pedido_id) DO UPDATE SET nota = EXCLUDED.nota, problemas = EXCLUDED.problemas,
        comentario = EXCLUDED.comentario, segmento = EXCLUDED.segmento, atualizado_em = now()
      RETURNING pedido_id, nota, problemas, comentario`,
    { p: pedidoId, e: String(alvo.executivo_id), n: String(nota), pr: problemas.join(','), c: comentario, s: alvo.segmento || '' });
    await dml(`INSERT INTO pedido_eventos (pedido_id, etapa, mensagem) VALUES (:p, 'avaliacao', :m)`,
      { p: pedidoId, m: `avaliado com nota ${nota}` + (problemas.length ? ` · ${problemas.map((x) => PROBLEMAS[x]).join(', ')}` : '') + (comentario ? ` · ${comentario}` : '') });
    return { ok: true, ...r[0] };
  }

  if (acao === 'despachar') return { ok: await acordarDespacho(mitra) };
  return { ok: false, erro: 'ACAO_INVALIDA', acao };
};

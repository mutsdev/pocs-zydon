// pipeline_poc — roda em segundo plano (executeAsync). Unica peca que fala com
// a internet: Zydon, Cloudflare, OpenRouter e sites dos clientes.
// Gerado por montar_funcao.mjs: driver.py e selecao.py vao embutidos abaixo.
const { createClient } = require('@mitralab.io/functions-sdk');
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const COMMIT = '__COMMIT__';
const DRIVER_PY = __DRIVER__;
const SELECAO_PY = __SELECAO__;
const ANEXO_PY = __ANEXO__;
const PACOTES_EXTRAS = ['pypdfium2', 'openpyxl', 'python-docx', 'xlrd'];
const FAIXAS_JSON = __FAIXAS__;
const RAIZ = '/tmp/zydon-pocs';
const REPO = `${RAIZ}/repo-${COMMIT}`;
const TRABALHO = `${RAIZ}/trabalho`;
const PARTE = 80000;
const SEGREDOS = ['ZYDON_POCS_CODE', 'ZYDON_POCS_TOKEN', 'CLOUDFLARE_ACCOUNT_ID',
  'CLOUDFLARE_API_TOKEN', 'OPENROUTER_API_KEY'];

let mitra;

__GUARDA__
const sql = async (texto, parametros = {}) => (await mitra.sql.executeQuery(texto, parametros)).rows || [];
const dml = async (texto, parametros = {}) => mitra.sql.executeDml([{ sql: texto, parameters: parametros }]);

function prepararRepositorio() {
  if (!fs.existsSync(`${REPO}/.pronto`)) {
    fs.mkdirSync(RAIZ, { recursive: true });
    execFileSync('python3', ['-c', `
import io, sys, zipfile, urllib.request, shutil, pathlib
url = "https://codeload.github.com/mutsdev/zydon-criar-pocs/zip/${COMMIT}"
dados = urllib.request.urlopen(url, timeout=120).read()
destino = pathlib.Path("${REPO}")
tmp = pathlib.Path("${RAIZ}/extraindo")
shutil.rmtree(tmp, ignore_errors=True)
zipfile.ZipFile(io.BytesIO(dados)).extractall(tmp)
raiz = next(tmp.iterdir())
shutil.rmtree(destino, ignore_errors=True)
raiz.rename(destino)
`], { stdio: 'pipe', timeout: 300000 });
    execFileSync('python3', ['-m', 'pip', 'install', '-q', '-r', `${REPO}/requirements.txt`],
      { stdio: 'pipe', timeout: 600000 });
    fs.writeFileSync(`${REPO}/.pronto`, new Date().toISOString());
  }
  if (!fs.existsSync(`${RAIZ}/.extras`)) {
    execFileSync('python3', ['-m', 'pip', 'install', '-q', ...PACOTES_EXTRAS], { stdio: 'pipe', timeout: 600000 });
    fs.writeFileSync(`${RAIZ}/.extras`, PACOTES_EXTRAS.join(' '));
  }
  fs.mkdirSync(`${RAIZ}/driver`, { recursive: true });
  fs.writeFileSync(`${RAIZ}/driver/driver.py`, DRIVER_PY);
  fs.writeFileSync(`${RAIZ}/driver/selecao.py`, SELECAO_PY);
  fs.writeFileSync(`${RAIZ}/driver/anexo.py`, ANEXO_PY);
  fs.writeFileSync(`${RAIZ}/driver/faixas_preco.json`, FAIXAS_JSON);
  fs.mkdirSync(TRABALHO, { recursive: true });
}

function rodarPython(acao, entrada, aoEvento) {
  const id = `${acao}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const arqEntrada = `${TRABALHO}/${id}-entrada.json`;
  const arqSaida = `${TRABALHO}/${id}-saida.json`;
  fs.writeFileSync(arqEntrada, JSON.stringify(entrada));
  const env = { ...process.env, ZYDON_REPO: REPO, ZYDON_TRABALHO: TRABALHO,
    PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' };
  return new Promise((resolve) => {
    const filho = spawn('python3', [`${RAIZ}/driver/driver.py`, acao, arqEntrada, arqSaida],
      { cwd: `${RAIZ}/driver`, env });
    let resto = '';
    let log = '';
    const eventos = [];
    const tratar = (bloco) => {
      resto += bloco.toString();
      const linhas = resto.split('\n');
      resto = linhas.pop();
      for (const linha of linhas) {
        if (linha.startsWith('EVENTO ')) {
          try { const ev = JSON.parse(linha.slice(7)); eventos.push(ev.mensagem); aoEvento(ev); } catch (e) { /* linha quebrada */ }
        } else { log = (log + linha + '\n').slice(-6000); }
      }
    };
    filho.stdout.on('data', tratar);
    filho.stderr.on('data', (b) => { log = (log + b.toString()).slice(-6000); });
    filho.on('close', (codigo, sinal) => {
      let saida;
      try { saida = JSON.parse(fs.readFileSync(arqSaida, 'utf-8')); } catch (e) {
        saida = { ok: false, erro: `driver saiu com código ${codigo} (sinal ${sinal}) sem resultado` };
      }
      for (const arq of [arqEntrada, arqSaida]) { try { fs.unlinkSync(arq); } catch (e) { /* ok */ } }
      saida.log = log.slice(-3000);
      saida.eventos = eventos.slice(-15);
      resolve(saida);
    });
  });
}

function registrador(pedidoId) {
  let fila = Promise.resolve();
  const registrar = (ev) => {
    fila = fila.then(() => dml(
      'INSERT INTO pedido_eventos (pedido_id, etapa, mensagem, nivel) VALUES (:p, :e, :m, :n)',
      { p: pedidoId, e: String(ev.etapa || 'pipeline'), m: String(ev.mensagem || '').slice(0, 1500),
        n: ['info', 'aviso', 'erro'].includes(ev.nivel) ? ev.nivel : 'info' })).catch(() => {});
    return fila;
  };
  registrar.fim = () => fila;
  return registrar;
}

async function salvarArquivo(pedidoId, tipo, conteudo) {
  await dml('DELETE FROM pedido_arquivos WHERE pedido_id = :p AND tipo = :t', { p: pedidoId, t: tipo });
  if (!conteudo) return;
  for (let i = 0; i * PARTE < conteudo.length; i += 1) {
    await dml(`INSERT INTO pedido_arquivos (pedido_id, tipo, parte, conteudo_base64)
      VALUES (:p, :t, CAST(:n AS INTEGER), :c)`,
    { p: pedidoId, t: tipo, n: String(i), c: conteudo.slice(i * PARTE, (i + 1) * PARTE) });
  }
}

async function lerArquivo(pedidoId, tipo) {
  const partes = await sql(`SELECT conteudo_base64 FROM pedido_arquivos
    WHERE pedido_id = :p AND tipo = :t ORDER BY parte`, { p: pedidoId, t: tipo });
  return partes.length ? partes.map((l) => l.conteudo_base64).join('') : null;
}

async function lerPedido(pedidoId) {
  const linhas = await sql(`SELECT p.pedido_id, p.cliente, p.site, p.segmento, p.segmento_origem,
      p.status, p.portal_id, p.portal_url, p.banner_cor, p.anexo_url, p.anexo_nome, p.logo_url,
      CAST(p.catalogo AS TEXT) AS catalogo, e.nome AS executivo
    FROM pedidos p JOIN executivos e ON e.id = p.executivo_id WHERE p.pedido_id = :p`, { p: pedidoId });
  if (!linhas.length) throw new Error(`pedido ${pedidoId} não existe`);
  const pedido = linhas[0];
  pedido.catalogo = pedido.catalogo ? JSON.parse(pedido.catalogo) : null;
  const logoNome = await sql(`SELECT conteudo_base64 FROM pedido_arquivos
    WHERE pedido_id = :p AND tipo = 'logo_nome'`, { p: pedidoId });
  const logo = await lerArquivo(pedidoId, 'logo');
  pedido.logo = logo && logoNome.length ? { nome: logoNome[0].conteudo_base64, conteudo_base64: logo } : null;
  return pedido;
}

async function marcarExecucao(pedidoId, acao, execucao) {
  await dml(`UPDATE pedidos SET execucao_atual = :x, execucao_acao = :a, execucao_desde = now(),
    atualizado_em = now() WHERE pedido_id = :p`, { p: pedidoId, a: acao, x: execucao || null });
}

async function falhar(pedidoId, erro, registrar) {
  await registrar({ etapa: 'pipeline', mensagem: erro, nivel: 'erro' });
  await dml(`UPDATE pedidos SET status = 'falhou', erro = :e, falhou_em = now(), atualizado_em = now(),
    execucao_atual = NULL WHERE pedido_id = :p`, { p: pedidoId, e: String(erro).slice(0, 3000) });
}

async function extrair(ev, execucao) {
  const pedidoId = ev.pedido_id;
  const registrar = registrador(pedidoId);
  const pedido = await lerPedido(pedidoId);
  if (!['extraindo', 'falhou', 'precisa_catalogo', 'aguardando_anexo'].includes(pedido.status)) {
    return { ok: true, ignorado: `pedido já está em ${pedido.status}` };
  }
  await dml(`UPDATE pedidos SET status = 'extraindo', erro = NULL, erro_codigo = NULL, commit_codigo = :c, atualizado_em = now()
    WHERE pedido_id = :p`, { p: pedidoId, c: COMMIT });
  await marcarExecucao(pedidoId, 'extrair', execucao);
  const conteudoAnexo = pedido.anexo_nome ? await lerArquivo(pedidoId, 'anexo') : null;
  if (pedido.anexo_nome && !conteudoAnexo) {
    await falhar(pedidoId, `o anexo ${pedido.anexo_nome} não chegou inteiro; envie de novo`, registrar);
    return { ok: false, erro: 'ANEXO_AUSENTE' };
  }
  const saida = await rodarPython('extrair', { pedido_id: pedidoId, cliente: pedido.cliente,
    site: pedido.site || '', segmento: '', executivo: pedido.executivo,
    anexo: conteudoAnexo ? { nome: pedido.anexo_nome, conteudo_base64: conteudoAnexo } : null }, registrar);
  await registrar.fim();
  if (!saida.ok) { await falhar(pedidoId, saida.erro, registrar); return saida; }
  if (saida.sem_credito) {
    await registrar({ etapa: 'extracao', mensagem: saida.sem_credito, nivel: 'erro' });
    await dml(`UPDATE pedidos SET status = 'falhou', erro_codigo = 'SEM_CREDITO_IA', erro = :e, falhou_em = now(),
      execucao_atual = NULL, atualizado_em = now() WHERE pedido_id = :p`, { p: pedidoId, e: saida.sem_credito });
    return { ok: false, erro: 'SEM_CREDITO_IA', motivo: saida.sem_credito };
  }
  if (saida.precisa_catalogo) {
    const custo = saida.custo || {};
    await dml(`UPDATE pedidos SET status = 'precisa_catalogo', motivo_catalogo = :m, modelo_ia = :mo,
      custo_ia_usd = CAST(:cu AS NUMERIC), tokens_ia = CAST(:t AS INTEGER), extracao_fim = now(),
      resumo = CAST(:r AS JSONB), execucao_atual = NULL, atualizado_em = now() WHERE pedido_id = :p`,
    { p: pedidoId, m: saida.precisa_catalogo, mo: custo.modelo || null, cu: String(custo.custo_usd || 0),
      t: String((custo.tokens_entrada || 0) + (custo.tokens_saida || 0)),
      r: JSON.stringify({ motivo: saida.precisa_catalogo, descartes: saida.descartes || [] }) });
    await registrar({ etapa: 'extracao', mensagem: `precisa de catálogo: ${saida.precisa_catalogo}`, nivel: 'aviso' });
    return { ok: true, status: 'precisa_catalogo', motivo: saida.precisa_catalogo };
  }
  const r = saida.resumo;
  if (saida.logo) {
    await salvarArquivo(pedidoId, 'logo', saida.logo.conteudo_base64);
    await salvarArquivo(pedidoId, 'logo_nome', saida.logo.nome);
  }
  await dml(`UPDATE pedidos SET status = 'curadoria', catalogo = CAST(:cat AS JSONB), resumo = CAST(:r AS JSONB),
      produtos = CAST(:np AS INTEGER), categorias = CAST(:nc AS INTEGER), fonte = :f, preco = :pr,
      segmento = :s, segmento_origem = :so, logo_url = :l, modelo_ia = :mo,
      custo_ia_usd = CAST(:cu AS NUMERIC), tokens_ia = CAST(:t AS INTEGER),
      produtos_similares = CAST(:sim AS BOOLEAN), observacoes = :o, extracao_fim = now(),
      nomes_lidos_na_imagem = CAST(:nl AS INTEGER),
      banners_situacao = :b, atualizado_em = now() WHERE pedido_id = :p`,
  { p: pedidoId, cat: JSON.stringify(saida.catalogo), r: JSON.stringify(r), np: String(r.produtos),
    nc: String(r.categorias), f: r.fonte, pr: r.preco, s: r.segmento, so: r.segmento_origem,
    l: saida.logo_url || null, mo: r.modelo, cu: String(r.custo_usd || 0), t: String(r.tokens || 0),
    sim: String(!!r.produtos_similares), o: r.observacoes || null, nl: String(r.nomes_lidos_na_imagem || 0),
    b: saida.logo ? 'gerando' : 'sem_banner' });
  if (saida.logo) await previa({ pedido_id: pedidoId }, execucao);
  await dml('UPDATE pedidos SET execucao_atual = NULL WHERE pedido_id = :p', { p: pedidoId });
  return { ok: true, status: 'curadoria', produtos: r.produtos, preco: r.preco };
}

async function gravarPecas(pedidoId, pecas, publicadas, cor) {
  const atual = await sql('SELECT COALESCE(MAX(geracao), 0) AS g FROM pecas_banner WHERE pedido_id = :p', { p: pedidoId });
  const geracao = Number(atual[0].g) + 1;
  for (const [peca, dados] of Object.entries(pecas || {})) {
    const pub = (publicadas || {})[peca] || {};
    await salvarArquivo(pedidoId, `previa:${peca}:${geracao}`, dados.previa_base64 || null);
    await dml(`INSERT INTO pecas_banner (pedido_id, peca, geracao, file_id, url, cor, previa_base64)
      VALUES (:p, :pe, CAST(:g AS INTEGER), :f, :u, :c, NULL)`,
    { p: pedidoId, pe: peca, g: String(geracao), f: pub.file_id || null, u: pub.url || null,
      c: cor || null });
  }
}

async function previa(ev, execucao) {
  const pedidoId = ev.pedido_id;
  const registrar = registrador(pedidoId);
  const pedido = await lerPedido(pedidoId);
  await marcarExecucao(pedidoId, 'previa', execucao);
  const saida = await rodarPython('previa', { pedido_id: pedidoId, cliente: pedido.cliente,
    segmento: pedido.segmento, catalogo: pedido.catalogo, logo: pedido.logo }, registrar);
  await registrar.fim();
  if (!saida.ok || saida.sem_banner) {
    const motivo = saida.sem_banner || saida.erro;
    await registrar({ etapa: 'banners', mensagem: `sem banner: ${motivo}`, nivel: 'aviso' });
    await dml(`UPDATE pedidos SET banners_situacao = 'sem_banner', observacoes = TRIM(COALESCE(observacoes, '') || ' · sem banner: ' || :m)
      WHERE pedido_id = :p`, { p: pedidoId, m: String(motivo).slice(0, 500) });
    return { ok: true, banners: 'sem_banner' };
  }
  await salvarArquivo(pedidoId, 'banners', saida.banners_tar);
  await gravarPecas(pedidoId, saida.pecas, null, saida.cor);
  await dml(`UPDATE pedidos SET banners_situacao = 'prontos', banner_cor = :c, atualizado_em = now()
    WHERE pedido_id = :p`, { p: pedidoId, c: saida.cor || null });
  return { ok: true, banners: 'prontos' };
}

async function pegarTrava(pedidoId, execucao) {
  const limite = Date.now() + 45 * 60 * 1000;
  while (Date.now() < limite) {
    const pega = await sql(`UPDATE travas SET pedido_id = :p, execucao_id = :x, desde = now()
      WHERE nome = 'criacao_portal' AND (pedido_id IS NULL OR pedido_id = :p OR desde < now() - interval '2 hours')
      RETURNING pedido_id`, { p: pedidoId, x: execucao || pedidoId });
    if (pega.length) return true;
    await new Promise((ok) => setTimeout(ok, 15000));
  }
  return false;
}

async function criar(ev, execucao) {
  const pedidoId = ev.pedido_id;
  const simular = !!ev.simular;
  const registrar = registrador(pedidoId);
  const antes = await lerPedido(pedidoId);
  if (antes.portal_id) return { ok: true, duplicado: true, portal_id: antes.portal_id, url: antes.portal_url };
  if (!simular) {
    const tomado = await sql(`UPDATE pedidos SET status = 'criando', criacao_inicio = now(),
        curadoria_fim = COALESCE(curadoria_fim, now()), atualizado_em = now()
      WHERE pedido_id = :p AND status = 'curadoria' AND portal_id IS NULL RETURNING pedido_id`, { p: pedidoId });
    if (!tomado.length) return { ok: true, ignorado: `pedido em ${antes.status}: nada a criar` };
  }
  await marcarExecucao(pedidoId, simular ? 'simular' : 'criar', execucao);
  await registrar({ etapa: 'criacao', mensagem: 'na fila: um portal por vez' });
  if (!(await pegarTrava(pedidoId, execucao))) {
    if (!simular) await falhar(pedidoId, 'fila de criação ocupada por mais de 45 minutos', registrar);
    return { ok: false, erro: 'fila ocupada' };
  }
  try {
    const pedido = await lerPedido(pedidoId);
    const banners = await lerArquivo(pedidoId, 'banners');
    const saida = await rodarPython('criar', { pedido_id: pedidoId, catalogo: pedido.catalogo,
      logo: pedido.logo, banners_tar: banners, simular }, registrar);
    await registrar.fim();
    const res = saida.resultado || {};
    if (simular) {
      await dml('UPDATE pedidos SET simulado = true, execucao_atual = NULL WHERE pedido_id = :p', { p: pedidoId });
      await registrar({ etapa: 'criacao', mensagem: `simulação: ${res.status || saida.erro} ${res.observacoes || ''}`,
        nivel: res.status === 'simulado' ? 'info' : 'erro' });
      return { ok: saida.ok && res.status === 'simulado', resultado: res, erro: saida.erro, log: saida.log };
    }
    if (!saida.ok || res.status !== 'concluido') {
      if (res.portal_id) {
        await dml('UPDATE pedidos SET portal_id = :id WHERE pedido_id = :p', { p: pedidoId, id: res.portal_id });
      }
      await falhar(pedidoId, saida.erro || res.observacoes || 'criação sem URL de portal', registrar);
      return { ok: false, erro: saida.erro || res.observacoes, log: saida.log };
    }
    await dml(`UPDATE pedidos SET status = 'concluido', portal_id = :id, portal_url = :u, concluido_em = now(),
        execucao_atual = NULL, atualizado_em = now(),
        observacoes = CASE WHEN :o = '' THEN observacoes ELSE TRIM(COALESCE(observacoes, '') || ' · ' || :o) END
      WHERE pedido_id = :p`, { p: pedidoId, id: res.portal_id, u: res.url, o: res.observacoes || '' });
    await registrar({ etapa: 'criacao', mensagem: `portal criado: ${res.url}` });
    if (saida.publicadas) {
      for (const [peca, pub] of Object.entries(saida.publicadas)) {
        await dml(`UPDATE pecas_banner SET file_id = :f, url = :u WHERE pedido_id = :p AND peca = :pe
          AND geracao = (SELECT MAX(geracao) FROM pecas_banner WHERE pedido_id = :p)`,
        { p: pedidoId, pe: peca, f: pub.file_id, u: pub.url || null });
      }
    } else if (saida.publicar_erro) {
      await registrar({ etapa: 'banners', mensagem: `peças não publicadas: ${saida.publicar_erro}`, nivel: 'aviso' });
    }
    return { ok: true, portal_id: res.portal_id, url: res.url };
  } finally {
    await dml("UPDATE travas SET pedido_id = NULL, execucao_id = NULL WHERE nome = 'criacao_portal' AND pedido_id = :p",
      { p: pedidoId });
  }
}

async function banner(ev, execucao) {
  const pedidoId = ev.pedido_id;
  const acao = ev.acao_banner;
  const registrar = registrador(pedidoId);
  const pedido = await lerPedido(pedidoId);
  if (acao === 'dispensar') {
    await dml("UPDATE pedidos SET banners_situacao = 'dispensado', atualizado_em = now() WHERE pedido_id = :p", { p: pedidoId });
    await registrar({ etapa: 'banners', mensagem: 'banners dispensados pelo usuário' });
    return { ok: true, banners: 'dispensado' };
  }
  if (acao === 'aplicar' && !pedido.portal_id) return { ok: false, erro: 'o portal ainda não existe' };
  await marcarExecucao(pedidoId, `banner:${acao}`, execucao);
  await dml('UPDATE pedidos SET banners_situacao = :b WHERE pedido_id = :p',
    { p: pedidoId, b: acao === 'aplicar' ? 'aplicando' : 'regerando' });
  const banners = await lerArquivo(pedidoId, 'banners');
  const saida = await rodarPython('banner', { pedido_id: pedidoId, acao_banner: acao, portal_id: pedido.portal_id,
    escolhas: ev.escolhas, pecas: ev.pecas, feedback: ev.feedback, cor: ev.cor, banners_tar: banners }, registrar);
  await registrar.fim();
  const encerrar = (situacao, extra = {}) => dml(`UPDATE pedidos SET banners_situacao = :b, execucao_atual = NULL,
    erro = COALESCE(:e, erro), atualizado_em = now() WHERE pedido_id = :p`, { p: pedidoId, b: situacao, e: extra.erro || null });
  if (!saida.ok) { await registrar({ etapa: 'banners', mensagem: saida.erro, nivel: 'erro' }); await encerrar('falhou', { erro: saida.erro }); return saida; }
  if (acao === 'aplicar') {
    const escolhas = ev.escolhas || {};
    const confere = (saida.relato || {}).confere || {};
    for (const [peca, fileId] of Object.entries(escolhas)) {
      await dml(`UPDATE pecas_banner SET aplicada = true, conferida_get = CAST(:c AS BOOLEAN), conferencia = :j
        WHERE pedido_id = :p AND peca = :pe AND file_id = :f`,
      { p: pedidoId, pe: peca, f: fileId, c: String(confere[peca] === true), j: JSON.stringify(saida.relato || saida) });
    }
    const todas = Object.keys(escolhas).every((peca) => confere[peca] === true);
    const situacao = saida.aplicado_parcial ? 'aplicado_parcial' : (todas ? 'aplicado' : 'falhou');
    await registrar({ etapa: 'banners', mensagem: todas ? 'banners aplicados e conferidos por GET'
      : `GET não confirmou: ${JSON.stringify(confere)}`, nivel: todas ? 'info' : 'erro' });
    await encerrar(situacao, todas ? {} : { erro: 'a Zydon não mostrou as peças no GET de conferência' });
    return { ok: todas, confere, situacao };
  }
  await salvarArquivo(pedidoId, 'banners', saida.banners_tar);
  await gravarPecas(pedidoId, saida.pecas, saida.publicadas, saida.cor);
  await dml('UPDATE pedidos SET banner_cor = :c WHERE pedido_id = :p', { p: pedidoId, c: saida.cor || null });
  await encerrar('prontos');
  return { ok: true, pecas: Object.keys(saida.pecas || {}) };
}

async function avaliar(ev) {
  const saida = await rodarPython('avaliar', { clientes: ev.clientes }, () => {});
  return saida;
}

const ACOES = { extrair, previa, criar, banner, avaliar };

module.exports = async (event, context) => {
  const ev = (event && event.input) ? event.input : (event || {});
  const acao = ev.acao;
  if (!ACOES[acao]) return { ok: false, erro: `ação desconhecida: ${acao}` };
  if (acao !== 'avaliar' && !ev.pedido_id) return { ok: false, erro: 'CAMPOS_FALTANDO', faltando: ['pedido_id'] };
  const faltando = SEGREDOS.filter((nome) => !process.env[nome]);
  mitra = createClient();
  await mitra.init();
  const g = await guarda(mitra, context);
  if (!g.ok) return g;
  if (!g.sessao.admin && !g.sessao.executivo_id) {
    return { ok: false, erro: 'EXECUTIVO_NAO_CADASTRADO', mensagem: 'Peça ao João Pedro para te cadastrar.' };
  }
  if (ev.pedido_id && !g.sessao.admin) {
    const dono = await sql('SELECT executivo_id FROM pedidos WHERE pedido_id = :p', { p: ev.pedido_id });
    if (!dono.length || Number(dono[0].executivo_id) !== Number(g.sessao.executivo_id)) {
      return { ok: false, erro: 'PEDIDO_DESCONHECIDO', pedido_id: ev.pedido_id };
    }
  }
  prepararRepositorio();
  const execucao = (context && context.executionId) || null;
  try {
    const resultado = await ACOES[acao](ev, execucao);
    return { ...resultado, commit: COMMIT, segredos_faltando: faltando };
  } catch (erro) {
    const texto = `${erro.name || 'Erro'}: ${erro.message}`;
    if (ev.pedido_id) {
      try {
        if (acao === 'previa' || acao === 'banner') {
          await registrador(ev.pedido_id)({ etapa: 'banners', mensagem: texto, nivel: 'erro' });
          await dml(`UPDATE pedidos SET banners_situacao = 'falhou', execucao_atual = NULL, atualizado_em = now()
            WHERE pedido_id = :p`, { p: ev.pedido_id });
        } else {
          await falhar(ev.pedido_id, texto, registrador(ev.pedido_id));
        }
      } catch (e) { /* banco fora */ }
      try {
        await dml("UPDATE travas SET pedido_id = NULL WHERE nome = 'criacao_portal' AND pedido_id = :p", { p: ev.pedido_id });
      } catch (e) { /* ok */ }
    }
    return { ok: false, erro: texto, commit: COMMIT, segredos_faltando: faltando };
  }
};

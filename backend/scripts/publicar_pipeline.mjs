// Publica o codigo da funcao pipeline_poc (funcao.js + driver.py + selecao.py + faixas_preco.json).
// Uso (cwd backend/): node scripts/publicar_pipeline.mjs
// Prepara o ambiente sozinho (npm install se faltar dependencia), roda a checagem do driver.py
// antes de publicar e confere depois que o codigo no ar e exatamente o montado.
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
const backend = new URL('..', import.meta.url).pathname;
if (!existsSync(`${backend}node_modules/dotenv`) || !existsSync(`${backend}node_modules/@mitralab.io/functions-sdk`)) {
  execFileSync('npm', ['install', '--no-audit', '--no-fund'], { cwd: backend, stdio: 'inherit' });
}
execFileSync('python3', [`${backend}scripts/checar_pipeline.py`], { stdio: 'inherit' });
const code = execFileSync('node', [`${backend}pipeline/montar_funcao.mjs`], { encoding: 'utf-8', maxBuffer: 1 << 26 });
const { getMitra } = await import('../mitra.js');
const mitra = await getMitra();
const secrets = ['ZYDON_POCS_CODE', 'ZYDON_POCS_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'NVIDIA_API_KEY', 'BARROSO_API_KEY', 'IMAGES_API_KEY'];
const lista = await mitra.functionsAdmin.list({ size: 100 });
const existente = (lista.content || lista.items || []).find((f) => f.name === 'pipeline_poc');
const descricao = 'Pipeline das POCs em segundo plano (extrair, previa, criar, banner, avaliar). Repositório zydon-criar-pocs fixado em 7b3d073.';
const f = existente
  ? await mitra.functionsAdmin.patch(existente.id, { code, secrets, description: descricao })
  : await mitra.functionsAdmin.create({ name: 'pipeline_poc', runtime: 'JAVASCRIPT', code, secrets, description: descricao });
const lida = await mitra.functionsAdmin.get(f.id);
const noAr = (lida.currentVersion && lida.currentVersion.code) || lida.code || '';
const confere = noAr === code;
console.log(JSON.stringify({ id: f.id, bytes: code.length, no_ar: noAr.length, confere }));
if (!confere) process.exit(1);

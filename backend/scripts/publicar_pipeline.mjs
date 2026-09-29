// Publica o codigo da funcao pipeline_poc (funcao.js + driver.py + selecao.py + faixas_preco.json).
// Uso (cwd backend/): node scripts/publicar_pipeline.mjs
import { execFileSync } from 'node:child_process';
import { getMitra } from '../mitra.js';
const code = execFileSync('node', [new URL('../pipeline/montar_funcao.mjs', import.meta.url).pathname], { encoding: 'utf-8', maxBuffer: 1 << 26 });
const mitra = await getMitra();
const secrets = ['ZYDON_POCS_CODE', 'ZYDON_POCS_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN', 'GEMINI_API_KEY', 'OPENROUTER_API_KEY', 'NVIDIA_API_KEY'];
const lista = await mitra.functionsAdmin.list({ size: 100 });
const existente = (lista.content || lista.items || []).find((f) => f.name === 'pipeline_poc');
const descricao = 'Pipeline das POCs em segundo plano (extrair, previa, criar, banner, avaliar). Repositório zydon-criar-pocs fixado em 7b3d073.';
const f = existente
  ? await mitra.functionsAdmin.patch(existente.id, { code, secrets, description: descricao })
  : await mitra.functionsAdmin.create({ name: 'pipeline_poc', runtime: 'JAVASCRIPT', code, secrets, description: descricao });
console.log(JSON.stringify({ id: f.id, bytes: code.length }));

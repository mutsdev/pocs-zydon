// Envia o frontend (replaceFiles), dispara o build e acompanha ate o fim. Uso (cwd backend/): node scripts/deploy.mjs
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { getMitra } from '../mitra.js';
const raiz = new URL('../../frontend/', import.meta.url).pathname;
const fora = new Set(['node_modules', 'dist', '.git']);
const binario = /\.(png|jpe?g|gif|ico|woff2?|ttf|eot|webp|pdf|zip)$/i;
const files = {};
(function andar(dir) {
  for (const nome of readdirSync(dir)) {
    if (fora.has(nome) || nome.startsWith('.env')) continue;
    const p = join(dir, nome);
    if (statSync(p).isDirectory()) andar(p);
    else if (!binario.test(nome) && !nome.endsWith('.tsbuildinfo')) files[relative(raiz, p)] = readFileSync(p, 'utf-8');
  }
})(raiz);
const mitra = await getMitra();
if (process.argv[2] === 'identidade') {
  await mitra.currentApp.update({ name: 'POCs Zydon', description: 'Portais de demonstração da Zydon: do site do cliente ao link do portal, com curadoria e relatórios por executivo.', color: { type: 'GRADIENT', startHex: '#28A7F8', endHex: '#1D9D6C' }, icon: 'Rocket01Icon' });
  console.log('identidade ok');
}
await mitra.currentApp.replaceFiles(files);
const d = await mitra.currentApp.build();
const id = d.id || d.deployId;
console.log('arquivos', Object.keys(files).length, 'deploy', id);
for (let i = 0; i < 90; i++) {
  await new Promise((ok) => setTimeout(ok, 5000));
  const s = await mitra.currentApp.getDeploy(id);
  if (!['BUILDING', 'PENDING', 'QUEUED'].includes(s.status)) {
    console.log(s.status, s.status === 'FAILED' ? String(s.logs || s.error).slice(-3000) : '');
    if (s.deployUrl || s.url) console.log('URL_INTERNA', s.deployUrl || s.url);
    break;
  }
}

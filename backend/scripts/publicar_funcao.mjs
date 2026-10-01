// Cria ou atualiza uma funcao JS a partir de funcoes/<nome>.js, embutindo funcoes/guarda.js no lugar de __GUARDA__.
// Uso (cwd backend/): node scripts/publicar_funcao.mjs <nome> "<descricao>"
import { readFileSync } from 'node:fs';
import { getMitra } from '../mitra.js';
const [nome, descricao] = process.argv.slice(2);
const guarda = readFileSync(new URL('../funcoes/guarda.js', import.meta.url), 'utf-8');
const dexter = readFileSync(new URL('../funcoes/dexter_nucleo.js', import.meta.url), 'utf-8');
const code = readFileSync(new URL(`../funcoes/${nome}.js`, import.meta.url), 'utf-8').replace('__GUARDA__', () => guarda).replace('__DEXTER__', () => dexter);
const mitra = await getMitra();
const lista = await mitra.functionsAdmin.list({ size: 100 });
const existente = (lista.content || lista.items || []).find((f) => f.name === nome);
const f = existente
  ? await mitra.functionsAdmin.patch(existente.id, { code, ...(descricao ? { description: descricao } : {}) })
  : await mitra.functionsAdmin.create({ name: nome, runtime: 'JAVASCRIPT', code, description: descricao });
console.log(JSON.stringify({ id: f.id, nome }));

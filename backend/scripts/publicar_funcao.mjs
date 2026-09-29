// Cria ou atualiza uma funcao JS a partir de funcoes/<nome>.js. Uso: node scripts/publicar_funcao.mjs <nome> "<descricao>"
import { readFileSync } from 'node:fs';
import { getMitra } from '../mitra.js';
const [nome, descricao] = process.argv.slice(2);
const code = readFileSync(new URL(`../funcoes/${nome}.js`, import.meta.url), 'utf-8');
const mitra = await getMitra();
const lista = await mitra.functionsAdmin.list({ size: 100 });
const existente = (lista.content || lista.items || []).find((f) => f.name === nome);
const f = existente
  ? await mitra.functionsAdmin.patch(existente.id, { code, description: descricao })
  : await mitra.functionsAdmin.create({ name: nome, runtime: 'JAVASCRIPT', code, description: descricao });
console.log(JSON.stringify({ id: f.id, nome }));

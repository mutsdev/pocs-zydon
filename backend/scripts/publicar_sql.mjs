// Publica funcoes/sql/<nome>.sql como funcoes SQL (cria ou atualiza). Uso (cwd backend/): node scripts/publicar_sql.mjs
import { readdirSync, readFileSync } from 'node:fs';
import { getMitra } from '../mitra.js';
const DS = 'ab636cb4-83a7-4c5f-8159-6c63afe6dc79';
const pasta = new URL('../funcoes/sql/', import.meta.url);
const mitra = await getMitra();
const lista = await mitra.functionsAdmin.list({ size: 100 });
const existentes = Object.fromEntries((lista.content || lista.items || []).map((f) => [f.name, f]));
for (const arq of readdirSync(pasta).filter((a) => a.endsWith('.sql')).sort()) {
  const nome = arq.replace(/\.sql$/, '');
  const code = readFileSync(new URL(arq, pasta), 'utf-8').trim();
  const f = existentes[nome]
    ? await mitra.functionsAdmin.patch(existentes[nome].id, { code })
    : await mitra.functionsAdmin.create({ name: nome, runtime: 'SQL', dataSourceId: DS, code, description: 'Sessão do usuário logado: e-mail, domínio, administrador e executivo.' });
  console.log(nome, f.id);
}

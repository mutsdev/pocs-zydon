// Gera frontend/src/lib/sf-ids.ts a partir da listagem de funcoes. Uso (cwd backend/): node scripts/gerar_sf_ids.mjs
import { writeFileSync } from 'node:fs';
import { getMitra } from '../mitra.js';
const mitra = await getMitra();
const lista = await mitra.functionsAdmin.list({ size: 100 });
const fns = (lista.content || lista.items || []).filter((f) => f.name !== 'pipeline_poc').sort((a, b) => a.name.localeCompare(b.name));
const linhas = fns.map((f) => `  ${f.name}: '${f.id}',`).join('\n');
writeFileSync(new URL('../../frontend/src/lib/sf-ids.ts', import.meta.url), `export const SF = {\n${linhas}\n} as const\n\nexport type SfNome = keyof typeof SF\n`);
console.log(fns.length);

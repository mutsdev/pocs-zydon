// Dispara uma funcao em segundo plano. Uso: node scripts/disparar.mjs <functionId> '<json>'
import { getMitra } from '../mitra.js';
const mitra = await getMitra();
const [id, entrada] = process.argv.slice(2);
const e = await mitra.functions.executeAsync(id, JSON.parse(entrada || '{}'));
console.log(JSON.stringify({ execucao: e.id, status: e.status }));

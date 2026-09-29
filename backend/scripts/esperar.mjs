// Dispara uma funcao em segundo plano e espera o fim. Uso: node scripts/esperar.mjs <functionId> '<json>' [segundos]
import { getMitra } from '../mitra.js';
const mitra = await getMitra();
const [id, entrada, limite] = process.argv.slice(2);
const e = await mitra.functions.executeAsync(id, JSON.parse(entrada || '{}'));
const fim = Date.now() + Number(limite || 300) * 1000;
let x = e;
while (Date.now() < fim) {
  await new Promise((ok) => setTimeout(ok, 4000));
  x = await mitra.functions.getExecution(e.id);
  if (!['RUNNING', 'PENDING', 'QUEUED'].includes(x.status)) break;
}
console.log(JSON.stringify({ execucao: e.id, status: x.status, ms: x.durationMs, erro: x.errorMessage, output: x.output }));

// Le uma execucao. Uso: node scripts/ver.mjs <executionId>
import { getMitra } from '../mitra.js';
const mitra = await getMitra();
const e = await mitra.functions.getExecution(process.argv[2]);
console.log(JSON.stringify({ status: e.status, ms: e.durationMs, erro: e.errorMessage, output: e.output }));

// Gera o codigo da funcao pipeline_poc: funcao.js com driver.py e selecao.py embutidos.
// Uso: node montar_funcao.mjs > /tmp/pipeline_poc.js
import { readFileSync } from 'node:fs';
const aqui = new URL('.', import.meta.url);
const ler = (nome) => readFileSync(new URL(nome, aqui), 'utf-8');
const COMMIT = '7b3d073427e47ecf660280920bfba23c3178834a';
process.stdout.write(ler('funcao.js')
  .replace("'__COMMIT__'", `'${COMMIT}'`)
  .replace('__DRIVER__', () => JSON.stringify(ler('driver.py')))
  .replace('__SELECAO__', () => JSON.stringify(ler('selecao.py')))
  .replace('__ANEXO__', () => JSON.stringify(ler('anexo.py')))
  .replace('__NAVEGADOR__', () => JSON.stringify(ler('navegador.py')))
  .replace('__FAIXAS__', () => JSON.stringify(ler('faixas_preco.json')))
  .replace('__GUARDA__', () => readFileSync(new URL('../funcoes/guarda.js', aqui), 'utf-8')));

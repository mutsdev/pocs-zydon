# Guia de Integração de Dados — Protocolo Obrigatório para IA

> **PROCEDÊNCIA:** cópia adaptada do guia de `brunobortp-netizen/guia-integracao-dados` (arquitetura antiga), alinhada à arquitetura atual do Mitra (cloud-native / PostgreSQL). A **importação periódica** (Data Loaders, `IMP_`, `LOAD DATA`/CSV recorrente) foi **removida** por não existir na versão atual — permanece só a **integração** (Data Source externa, Tabela Online/Custom Query, Function API e Cloudflare Tunnel configurado pela interface). O que foi removido está registrado em `FEATURES-SUSPENSAS.md`.

> **REGRA FUNDAMENTAL:** Este guia é um protocolo de alinhamento com o usuário. A IA NÃO PODE escrever código de integração antes de completar TODAS as fases de alinhamento e receber confirmação explícita no checkpoint final. A IA é a executora, o usuário é o arquiteto da decisão.

> **ROTEAMENTO DE AUTORIA:** use MCP para templates, credenciais, Integration configs, SQL, schema e Server Functions suportadas pelas 38 tools do chat. Use o Functions SDK apenas quando o recurso não existir no catálogo reduzido: Data Source externa, Tabela Online ou criação e atualização de uma Function com runtime `API`. Descubra as tools e leia o schema em runtime. Nunca substitua uma operação coberta pelo MCP por SDK ou HTTP. Cloudflare Tunnel não existe no MCP reduzido nem no Functions SDK; informe a lacuna e direcione o usuário ao fluxo suportado da plataforma.

---

## Modo de Operação: Integração Nova vs Revisão de Existente

> **REGRA CRÍTICA:** Este protocolo se aplica TANTO para criar integrações novas QUANTO para revisar/corrigir integrações já implementadas. Em NENHUM cenário a IA pode sair codando sem alinhar.

### Se o pedido é CRIAR uma integração nova:
→ Seguir Fases 1 → 2 → 3 → 4 → 5 sequencialmente.

### Se o pedido é REVISAR ou CORRIGIR uma integração existente:

**A IA DEVE seguir este fluxo antes de alterar qualquer código:**

1. **Auditar:** Levantar tudo que já existe (SFs, integrações, JDBCs, tabelas, queries) e comparar com as regras deste guia
2. **Listar problemas:** Apresentar ao usuário uma lista clara de cada item que está em desacordo com as boas práticas, explicando o risco de cada um (ex: "A SF chama `fetch` direto para uma API externa em vez de usar uma Function API")
3. **Propor correções:** Para cada problema, sugerir a correção e perguntar ao usuário se concorda
4. **Alinhar itens pendentes:** Verificar se as Fases 1-3 foram cobertas na integração atual — se não, levantar como pendência e alinhar com o usuário
5. **Checkpoint:** Gerar o Contrato de Integração revisado (Fase 4) com todas as correções planejadas e pedir confirmação explícita
6. **Só então:** Implementar as correções aprovadas

### Checklist obrigatório de auditoria de integração existente

Ao auditar uma integração existente, a IA DEVE verificar TODOS os itens abaixo e listar cada violação ao usuário:

**🔴 Sinais críticos (perda de dados / problemas graves):**
- [ ] **Uso de `mitra.entities` no frontend para dados de integração** → PROIBIDO. Entities é só para CRUD simples de tabelas locais em tela dev. Para integração, use SF SQL ou Function API via `mitra.functions`
- [ ] **SQL direto no frontend** → PROIBIDO em integrações. Frontend deve usar SF SQL com `mitra.functions.execute()`
- [ ] Uso de `fetch`/`axios` direto em SF JavaScript para chamar APIs externas (deve usar Function API)
- [ ] Tokens hardcoded no código das SFs

**🟡 Sinais de qualidade (otimização / boas práticas):**
- [ ] Múltiplas SFs com JOINs idênticos (deveria usar Tabela Online)

**🟢 Sinais de discovery incompleto:**
- [ ] Dados sample misturados com dados reais
- [ ] Tipos de coluna incompatíveis entre fonte e destino
- [ ] Não foi alinhado o modelo de consumo (Online / tempo real) com o usuário

> **PROIBIDO:** Ao receber pedido de revisão/correção, sair alterando código diretamente. SEMPRE auditar → listar → alinhar → checkpoint → implementar.

> **PROIBIDO em integrações:** `mitra.entities` e SQL direto no frontend NÃO devem consumir dados externos. Toda integração deve ser consumida via Server Functions SQL ou API, executadas por `mitra.functions`. Ao auditar, este é um dos primeiros itens a verificar.

---

## Índice

1. [Fase 1 — Discovery](#fase-1--discovery)
2. [Fase 2 — Decisão de Arquitetura](#fase-2--decisão-de-arquitetura)
3. [Fase 3 — Alinhamento Técnico Detalhado](#fase-3--alinhamento-técnico-detalhado)
4. [Fase 4 — Checkpoint de Consenso](#fase-4--checkpoint-de-consenso)
5. [Fase 5 — Implementação](#fase-5--implementação)
6. [Referência de autoria](#referência-de-autoria)

---

## Fase 1 — Discovery

```
┌─────────────────────────────────────────────────┐
│           PERGUNTAS OBRIGATÓRIAS                │
│         (todas devem ser respondidas)            │
└─────────────────────────────────────────────────┘
```

A IA DEVE fazer TODAS estas perguntas antes de avançar:

### 1.1 Sobre a Fonte de Dados
- [ ] **Qual é o sistema/fonte?** (ERP, CRM, banco externo, API, planilha CSV?)
- [ ] **Qual o tipo de acesso?** (banco de dados direto via JDBC? API REST? arquivo exportado?)
- [ ] **O sistema fonte é acessível pela internet ou está on-premise?** (se on-premise, vai precisar de Cloudflare Tunnel)
- [ ] **Você tem credenciais de leitura disponíveis?** (usuário read-only no banco? API key? token?)
- [ ] **Existe documentação da estrutura de dados?** (dicionário de dados, docs de API, schema do banco?)

### 1.2 Sobre o Volume e Uso
- [ ] **Qual o volume estimado de dados?** (centenas, milhares, milhões de registros?)
- [ ] **Quantos registros novos/alterados por dia?**
- [ ] **Quantos usuários vão consumir esses dados nos dashboards?**
- [ ] **Os dados são usados para análise/BI ou para operação transacional?**

### 1.3 Sobre a Necessidade de Atualização
- [ ] **Com que frequência os dados precisam estar atualizados?** (real-time, a cada hora, diário, semanal?)
- [ ] **Existe tolerância a delay?** (ex: "dados do dia anterior está ok" vs "preciso ver o pedido que acabou de entrar")
- [ ] **Existe janela de baixo uso do sistema fonte?** (madrugada, fim de semana? — para full syncs pesados)

### 1.4 Sobre Transformações
- [ ] **Os dados vêm prontos ou precisam de tratamento?** (joins, cálculos, limpeza, normalização?)
- [ ] **Existem regras de negócio que precisam ser aplicadas nos dados?** (classificações, agrupamentos, conversões?)

### 1.5 Sobre Estado Atual do Projeto
- [ ] **O projeto já possui tabelas com dados sample/fictícios?** (cenário muito comum: o sistema já foi construído com dados de exemplo e agora quer conectar ao ERP real)
- [ ] **Se sim: quais tabelas já existem e qual a estrutura delas?** (listar tabelas, colunas, tipos)
- [ ] **Podemos deletar todos os dados sample dessas tabelas para substituir pela integração real?** (perguntar explicitamente, ex: "Posso limpar os dados fictícios das tabelas CLIENTES, PEDIDOS, PRODUTOS e substituir pela importação automatizada do ERP?")
- [ ] **Existe algum dado que NÃO deve ser deletado?** (ex: configurações, tabelas de apoio que foram preenchidas manualmente)

> **PROIBIDO:** Avançar para Fase 2 sem resposta para TODAS as perguntas acima. Se o usuário não souber alguma, a IA deve ajudá-lo a descobrir ou registrar como pendência a ser investigada.

---

## Fase 2 — Decisão de Arquitetura

```
┌──────────────────────────────────────────────────────────────────────┐
│                    ÁRVORE DE DECISÃO                                │
│                                                                      │
│  ┌──────────┐     ┌───────────────┐     ┌─────────────────────┐     │
│  │  Fonte   │────▶│  Tipo de      │────▶│  Modelo escolhido   │     │
│  │  dados   │     │  acesso       │     │  pelo USUÁRIO       │     │
│  └──────────┘     └───────────────┘     └─────────────────────┘     │
│                                                                      │
│  A IA SUGERE, mas o USUÁRIO DECIDE                                  │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.1 Modelo de Consumo

Na versão atual, o consumo de dados externos é **Online / tempo real** (a importação periódica está suspensa — ver `FEATURES-SUSPENSAS.md`). Apresente o modelo ao usuário com prós e contras:

#### Modelo A — Online / Tempo Real
```
Usuário acessa dashboard → SF consulta fonte externa na hora → Dados frescos
```

| Prós | Contras |
|------|---------|
| Dados sempre atualizados | Cada acesso gera carga no ERP/sistema fonte |
| Sem necessidade de rotina de importação | Latência maior (depende da fonte) |
| Sem armazenamento duplicado | Se a fonte cair, o dashboard fica fora |
| Mais simples de implementar | Muitos usuários simultâneos podem travar o ERP |

**Quando sugerir:** poucos usuários, dados leves, cliente aceita carga no ERP, sistema fonte estável e rápido.

**Implementação técnica:**
- SF tipo SQL com `dataSourceId` apontando para a Data Source externa
- Ou Function API para APIs REST
- Usar Tabelas Online para centralizar queries complexas. Como esse recurso não existe no MCP reduzido, sua autoria usa a fallback Functions SDK limitada

### 2.2 Subtipos de Fonte — Perguntas Adicionais

#### Se a fonte é banco de dados (JDBC):
- [ ] Qual o tipo? (MySQL, PostgreSQL, Oracle, SQL Server?)
- [ ] **O banco é acessível pela internet ou está on-premise?** Se for on-premise, explique que Cloudflare Tunnel não pode ser criado pelo MCP reduzido nem pelo Functions SDK. Trate como lacuna de capacidade e oriente o usuário a configurar o túnel no fluxo suportado da plataforma antes de continuar.
- [ ] Existe usuário read-only?
- [ ] Quais as queries/views que trazem os dados desejados?

**Fluxo obrigatório para descobrir as queries:**
1. **Perguntar primeiro:** "Você já tem as queries SQL prontas ou quer que eu ajude a construir?"
2. **Se o usuário tem queries:** usar as que ele fornecer. Validar com `LIMIT 10` antes de criar a SF.
3. **Se o usuário NÃO tem queries:** perguntar: "Quer que eu pesquise na documentação oficial do [nome do ERP/sistema] as queries e tabelas adequadas para extrair esses dados?"
   - Se sim: buscar na internet a documentação do sistema (ex: "Sankhya tabelas financeiro", "TOTVS Protheus tabela SE1", "SAP BKPF BSEG")
   - Apresentar ao usuário o que encontrou e validar antes de usar
   - Se não encontrar docs: pedir para o usuário consultar o time de TI do ERP ou explorar o schema do banco juntos

> **IMPORTANTE:** Nunca inventar queries baseado em suposições. Se não tem certeza da estrutura, SEMPRE validar com o usuário ou pesquisar na documentação oficial.

#### Se a fonte é API REST:
- [ ] Existe template de integração Mitra disponível? (listar com a tool MCP `listIntegrationTemplates`)
- [ ] Qual a autenticação? (API Key, Bearer Token, OAuth2, Basic Auth?)
- [ ] Qual o rate limit da API? (quantas chamadas por minuto/hora?)
- [ ] Existe paginação? Qual o limite por chamada?
- [ ] **Qual endpoint será utilizado?** Alinhar com o usuário — diferentes endpoints têm diferentes limites e comportamentos (ex: na Sankhya, o endpoint `DbExplorerSP.executeQuery` tem limite de 5.000 linhas por chamada, mas outros endpoints podem não ter essa restrição)
- [ ] Qual o endpoint que retorna os dados? Existe endpoint de listagem com filtros?

> **Fonte CSV / importação de arquivo:** a importação de CSV (recorrente ou avulsa) depende do mecanismo de importação, **suspenso na versão atual** — ver `FEATURES-SUSPENSAS.md`. Para dados de arquivo hoje, alinhe com o usuário uma alternativa via integração (JDBC/API) ou aguarde a volta da importação.

---

## Fase 3 — Alinhamento Técnico Detalhado

> Esta fase é a mais crítica. A IA DEVE questionar o usuário sobre CADA item abaixo e registrar as decisões.

### 3.1 Queries e Mapeamento de Dados

- [ ] **Quais queries/endpoints serão usados?** (o usuário fornece? vamos descobrir a partir da estrutura do banco?)
- [ ] **Quais colunas são necessárias?** (trazer tudo `SELECT *` ou apenas colunas específicas?)
- [ ] **Como mapear os nomes?** (CODPARC → ID_PARCEIRO? manter nomes originais?)
- [ ] **Quais os tipos corretos?** (INT, VARCHAR, DECIMAL, DATE, DATETIME?)
- [ ] **Existem JOINs necessários?** (dados vêm de várias tabelas da fonte?)

#### 3.1.1 Teste Prévio Obrigatório das Queries

> **REGRA OBRIGATÓRIA:** Antes de criar qualquer SF que consulte a fonte, a IA DEVE executar a query da fonte com `LIMIT 10` (ou equivalente) para validar que retorna o esperado.

**Fluxo obrigatório:**
1. Executar a query com LIMIT para inspecionar os dados reais
2. Apresentar ao usuário: "A query retorna essas colunas com esses tipos: [lista]. Está correto?"
3. Só depois de confirmado: criar a SF definitiva

**Exemplo via SF SQL temporária para teste (com `dataSourceId` da Data Source externa):**
```sql
-- Testar query da fonte via SF SQL com dataSourceId externo
SELECT * FROM PEDIDOS_ERP WHERE 1=1 LIMIT 10
```

#### 3.1.2 Mapeamento e Validação de Tipos (Cenário Sample → Produção)

> **CENÁRIO CRÍTICO:** Se o projeto já tem tabelas com dados sample, é OBRIGATÓRIO validar a compatibilidade de tipos antes de importar dados reais. Ignorar isso causa bugs silenciosos (ex: IDs não populados porque a coluna era INT mas a query retorna VARCHAR).

**Fluxo obrigatório quando existem tabelas sample:**

1. **Listar estrutura das tabelas existentes:**
```sql
-- Via SF SQL no banco do app (dataSourceId da fonte padrão)
DESCRIBE CLIENTES;
-- ou
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'CLIENTES'
ORDER BY ORDINAL_POSITION;
```

2. **Comparar com o retorno da query da fonte (do LIMIT 10):**

```
┌─────────────────────────────────────────────────────────────────┐
│  DE-PARA: Query Fonte → Tabela Existente                       │
├─────────────┬──────────────┬──────────────┬────────────────────┤
│ Coluna ERP  │ Tipo ERP     │ Coluna Mitra │ Tipo Mitra         │
├─────────────┼──────────────┼──────────────┼────────────────────┤
│ CODPARC     │ VARCHAR(20)  │ ID           │ INT  ⚠️ INCOMP.    │
│ RAZAO       │ VARCHAR(200) │ NOME         │ VARCHAR(100) ⚠️    │
│ DT_CAD      │ DATETIME     │ DT_CADASTRO  │ DATE  ⚠️ PREC.    │
│ ATIVO       │ CHAR(1)      │ (não existe) │ — CRIAR            │
└─────────────┴──────────────┴──────────────┴────────────────────┘
```

3. **Apresentar ao usuário e pedir confirmação:**
   - "Encontrei essas incompatibilidades de tipo. Posso ajustar as tabelas existentes com ALTER TABLE?"
   - "A coluna CODPARC é VARCHAR no ERP mas INT na sua tabela. Posso alterar para VARCHAR(20)?"
   - "A coluna ATIVO não existe na sua tabela. Posso adicioná-la?"

4. **Executar os ajustes ANTES de importar:** use `executeDdl` ou `executeDdlBatch` do MCP com SQL PostgreSQL validado. Não use a SDK para DDL.

```sql
ALTER TABLE clientes ALTER COLUMN id TYPE VARCHAR(20);
ALTER TABLE clientes ADD COLUMN ativo CHAR(1) DEFAULT 'S';
```

5. **Limpar dados sample (com confirmação do usuário):** use `executeDml` ou `executeDmlBatch` do MCP somente após confirmação explícita.

```sql
DELETE FROM clientes WHERE id IS NOT NULL;
DELETE FROM pedidos WHERE id IS NOT NULL;
```

> **PROIBIDO:**
> - Nunca ignorar incompatibilidades de tipo silenciosamente. Se a coluna da fonte é VARCHAR e a tabela é INT, a importação pode falhar ou perder dados SEM erro visível.
> - Nunca deletar dados sample sem perguntar ao usuário.
> - Nunca pular colunas da query fonte sem informar o usuário (ex: "a query retorna CODPARC mas não vou importar porque não tem coluna correspondente" — ERRADO, deve perguntar).

## Fase 4 — Checkpoint de Consenso

> **REGRA ABSOLUTA:** A IA DEVE gerar este resumo e pedir confirmação EXPLÍCITA antes de codar.

### Template de Contrato de Integração

A IA deve preencher e apresentar ao usuário:

```
╔══════════════════════════════════════════════════════════╗
║            CONTRATO DE INTEGRAÇÃO — RESUMO              ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  FONTE: [nome do sistema/ERP]                           ║
║  TIPO DE ACESSO: [JDBC / API REST]                      ║
║  MODELO: Online / tempo real                            ║
║                                                          ║
║  TABELAS/ENTIDADES:                                     ║
║  ┌──────────────┬──────────┬────────────────────────┐   ║
║  │ Entidade     │ Volume   │ Query / endpoint fonte │   ║
║  ├──────────────┼──────────┼────────────────────────┤   ║
║  │ Clientes     │ ~10k     │ SELECT ... FROM ...    │   ║
║  │ Pedidos      │ ~500k    │ GET /api/pedidos       │   ║
║  └──────────────┴──────────┴────────────────────────┘   ║
║                                                          ║
║  CONSUMO: SF SQL (Data Source) / Function API            ║
║                                                          ║
║  TABELAS ONLINE: [entidades que centralizam JOINs]      ║
║                                                          ║
║  ON-PREMISE: [Cloudflare Tunnel? sim/não]               ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝

Confirma que posso implementar seguindo EXATAMENTE este plano?
```

> **PROIBIDO:** Começar a implementar sem a confirmação explícita do usuário neste checkpoint. Se o usuário tiver qualquer dúvida, VOLTA para a fase relevante.

---

## Fase 5 — Implementação

> Somente após confirmação no Checkpoint da Fase 4.

> Nesta versão, a implementação cobre **consumo Online**: SF SQL sobre Data Source/Tabela Online (fonte banco) e Function API (fonte API REST, abaixo). A implementação de importação periódica está suspensa — ver `FEATURES-SUSPENSAS.md`.

### 5.1 Fluxo de Implementação — API REST (Integration)

```
┌──────────────┐     ┌───────────────┐     ┌────────────────┐     ┌────────────┐
│ 1. Listar    │────▶│ 2. Testar     │────▶│ 3. Criar       │────▶│ 4. Criar   │
│ templates    │     │ conexão       │     │ Integration    │     │ SF tipo    │
│              │     │               │     │                │     │ runtime API│
└──────────────┘     └───────────────┘     └────────────────┘     └────────────┘
```

1. Descubra `listIntegrationTemplates`, leia seu schema e liste os templates.
2. Inspecione o escolhido com `getIntegrationTemplate` e teste as credenciais com `testIntegrationCredentials`.
3. Crie a config com `createIntegrationConfig` e valide a config salva com `testIntegrationConfig`.
4. Como o MCP reduzido não cria o runtime `API`, use a fallback Functions SDK limitada somente para essa Function:

```javascript
const fn = await mitra.functionsAdmin.create({
  name: 'buscar_clientes_api',
  runtime: 'API',
  code: JSON.stringify({
    alias: 'erp-api',
    method: 'POST',
    endpoint: '/api/query',
    body: {
      query: "SELECT * FROM CLIENTES WHERE DT_ALT >= {{ultimaSync}}"
    }
  }),
  description: 'Busca clientes na API do ERP'
});
await mitra.functionsAdmin.publish(fn.id);
```

O `alias` deve ser o slug real retornado pela Integration config criada via MCP. Nunca repita credenciais no código da Function.

> **Params em Function API:** use `{{nomeVariavel}}` no code, com o valor vindo do segundo argumento de `mitra.functions.executeAsync(id, input)`. **NUNCA interpole valor do usuário final** — a substituição não é bind. Para filtro escolhido pelo usuário, use SF JAVASCRIPT com validação ou Data Source + SF SQL com bind real. Ver a seção de Server Functions no system prompt.

**Para APIs com paginação (ex: Sankhya endpoint `DbExplorerSP.executeQuery` com limite de 5.000 linhas — alinhar com o usuário qual endpoint será utilizado, pois cada um tem limites diferentes):**
<!-- pagination-sf-example:start -->
```javascript
// SF JAVASCRIPT que orquestra paginação
const code = `
const { createClientFromEnvironment } = require('@mitralab.io/functions-sdk');
const sourceFunctionId = ${JSON.stringify(String(sfIntegrationId))};
const pollingIntervalMs = 2000;
const pollingTimeoutMs = 5 * 60 * 1000;

exports.handler = async () => {
  const mitra = createClientFromEnvironment();
  await mitra.init();

  let offset = 0;
  const limit = 5000;
  let processedRows = 0;
  let hasMore = true;

  while (hasMore) {
    const accepted = await mitra.functions.executeAsync(sourceFunctionId, { offset, limit });
    const deadline = Date.now() + pollingTimeoutMs;
    let completed = await mitra.functions.getExecution(accepted.id);

    while (['PENDING', 'RUNNING'].includes(completed.status)) {
      if (Date.now() >= deadline) {
        throw new Error('Function execution ' + accepted.id + ' timed out');
      }
      await new Promise((resolve) => setTimeout(resolve, pollingIntervalMs));
      completed = await mitra.functions.getExecution(accepted.id);
    }

    if (completed.status === 'FAILED') {
      throw new Error(completed.errorMessage || ('Function execution ' + accepted.id + ' failed'));
    }
    if (completed.status === 'CANCELLED') {
      throw new Error('Function execution ' + accepted.id + ' was cancelled');
    }
    if (completed.status !== 'SUCCESS') {
      throw new Error('Unexpected Function status: ' + completed.status);
    }

    const rows = completed.output?.body?.rows;
    if (!Array.isArray(rows)) {
      throw new Error('Function output.body.rows must be an array');
    }
    if (rows.length === 0) break;

    // Inserir lote na tabela local
    // ... upsert logic ...

    processedRows += rows.length;
    offset += limit;
    hasMore = rows.length === limit;
  }

  return { processedRows };
};
`;
```
<!-- pagination-sf-example:end -->

---

## Referência de autoria

### Operações cobertas pelo MCP

| Domínio | Tools de autoria |
|--------|-----|
| Server Functions | `listFunctions`, `getFunction`, `createFunction`, `updateFunction`, `deleteFunction`, `bulkCreateFunctions`, `bulkUpdateFunctions`, `bulkDeleteFunctions`, `executeFunction`, `getExecution`, `listExecutions` |
| SQL e schema | `listTables`, `executeQuery`, `executeDml`, `executeDmlBatch`, `executeDdl`, `executeDdlBatch` |
| Integration configs | `listIntegrationTemplates`, `getIntegrationTemplate`, `listIntegrationConfigs`, `getIntegrationConfig`, `createIntegrationConfig`, `updateIntegrationConfig`, `deleteIntegrationConfig`, `bulkCreateIntegrationConfigs`, `bulkUpdateIntegrationConfigs`, `bulkDeleteIntegrationConfigs`, `testIntegrationCredentials`, `testIntegrationConfig` |

Essas operações são MCP-only durante a autoria. Descubra a tool e leia seu schema em runtime. Não use a SDK como alternativa.

### Fallback Functions SDK limitada para Server Function

| Função | Uso |
|--------|-----|
| `mitra.functionsAdmin.create({ name, runtime: 'API', code, description })` | Cria apenas a Function API que o MCP reduzido ainda não suporta |
| `mitra.functionsAdmin.patch(id, input)` | Atualiza apenas uma Function existente com runtime `API` |
| `mitra.functionsAdmin.publish(id)` | Publica a versão DRAFT após create ou patch |
| `mitra.functionsAdmin.setVisibility(id, 'PUBLIC' | 'PRIVATE')` | Configura acesso público, ausente do MCP, depois de confirmação explícita |

Execução, leitura e CRUD dos tipos suportados continuam no MCP. No frontend gerado, `mitra.functions.execute()` permanece válido como SDK de runtime.

### Data Sources externas (backend: `@mitralab.io/functions-sdk`)

| Função | Uso |
|--------|-----|
| `mitra.dataSources.create(input)` | Cria fonte `EXTERNAL`; credencial é write-only |
| `mitra.dataSources.update(id, input)` | Atualiza fonte; credencial omitida é preservada |
| `mitra.dataSources.list(options?)` / `get(id)` / `delete(id)` | Lista, lê metadados seguros e remove |

### Query no frontend (`@mitralab.io/platform-sdk`)

| Função | Uso |
|--------|-----|
| `mitra.functions.execute(functionId, input?)` | Caminho padrão para telas business; leia `execution.output` |
| `mitra.queries.execute(customQueryId, parameters?)` | Executa Custom Query autorizada e retorna `{ rows, affectedRows?, durationMs }` |

### Funções de Upload (frontend: `@mitralab.io/platform-sdk`)

| Função | Uso |
|--------|-----|
| Upload público | O Platform SDK nativo não expõe upload público. Não invente método nem use o legado; siga o fluxo suportado de assets documentado no system prompt ou alinhe com o usuário quando upload público real for requisito. |

### Tabelas Online (backend: `@mitralab.io/functions-sdk`)

| Função | Uso |
|--------|-----|
| `mitra.customQueries.create({ name, sql, isVirtualTable: true, connectionId })` | Cria Tabela Online parametrizada |
| `mitra.customQueries.update(id, input)` | Substitui; `name` e `sql` obrigatórios, `isVirtualTable?` e `connectionId?` opcionais |
| `mitra.customQueries.list(options?)` | Lista summaries em `Page.content` |
| `mitra.customQueries.get(id)` | Lê SQL completo antes de criar SF consumidora |

### Cloudflare Tunnel

Cloudflare Tunnel é uma lacuna desta variante: as 38 tools MCP não cobrem sua autoria e o `@mitralab.io/functions-sdk` fixado no template não exporta operações de Tunnel (`verified in the fixed package types`). Não invente nomes de tools ou funções SDK.

Quando uma fonte on-premise exigir Tunnel, explique a limitação e peça que o usuário conclua a configuração pelo fluxo suportado da plataforma. Não solicite credenciais do banco no chat. Retome a implementação somente depois que a conexão JDBC estiver disponível para inspeção.

### Cron — Spring Cron 6 campos

```
segundo minuto hora diaMes mes diaSemana
  0      */30   6-22   *    *      *       → a cada 30min das 6h às 22h
  0       0      3     *    *      *       → diário às 3h
  0       0     */2    *    *      *       → a cada 2h
  0      */5     *     *    *      *       → a cada 5min (mínimo permitido)
```

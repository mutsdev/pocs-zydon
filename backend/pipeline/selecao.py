"""Extracao por IA restrita a candidatos coletados.

O modelo so ESCOLHE entre candidatos com URL de origem e imagem da mesma fonte.
Nome, URL, imagem e preco saem sempre do candidato; do modelo saem apenas os
indices, a categoria e o julgamento "e da marca do cliente?". Modelo fixado por
id exato (nunca alias "latest").
"""

import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

MODELO_SELECAO = "google/gemini-2.5-flash"
MINIMO_PRODUTOS = 5
MAXIMO_PRODUTOS = 12
MAXIMO_CANDIDATOS = 60
MAXIMO_IMAGENS_NO_PROMPT = 40
MAXIMO_TOKENS_SAIDA = 4000

NAO_E_PRODUTO = re.compile(
    r"\b(arrow|seta|previous|next|anterior|proximo|slide|slider|banner|carrossel|"
    r"carousel|logo|logotipo|icone|icon|favicon|whatsapp|instagram|facebook|"
    r"youtube|mapa|map|avatar|placeholder|background|fundo|hero)\b", re.I)
IMAGEM_NAO_E_PRODUTO = re.compile(
    r"(/slider/|/slides?/|/banners?/|/icons?/|logo|favicon|sprite|placeholder|\.svg($|\?))", re.I)


class PrecisaCatalogo(RuntimeError):
    """Menos de MINIMO_PRODUTOS validos: o executivo manda PDF ou planilha."""


def evento(etapa, mensagem, nivel="info"):
    print("EVENTO " + json.dumps({"etapa": etapa, "mensagem": mensagem, "nivel": nivel},
                                 ensure_ascii=False), flush=True)


def sem_acento(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


def nome_valido(nome, url=""):
    """Codigo sem espaco ("SUP390") so vale com pagina de produto propria;
    na home e nome de arquivo de slide ("biscoito2", "pizza-1")."""
    nome = (nome or "").strip()
    if len(nome) < 4 or not re.search(r"[A-Za-zÀ-ú]{2}", nome):
        return False
    pagina_propria = len([p for p in urlparse(url or "").path.split("/") if p]) >= 1
    if " " not in nome and re.search(r"\d", nome) and not pagina_propria:
        return False
    return not NAO_E_PRODUTO.search(sem_acento(nome))


def normalizar_site(site):
    base = site if site.startswith(("http://", "https://")) else "https://" + site
    return base.rstrip("/") + "/"


UA_ALTERNATIVO = {"User-Agent": "Mozilla/5.0"}


def _get_com_retentativa(original):
    """Loja Integrada devolve 403 ao UA "Chrome/128" do coletor e 200 ao
    "Mozilla/5.0" (medido em 28/09/2026). Repete uma vez com o outro UA."""
    import requests
    import coletar_site

    def _get(url, **kw):
        resposta = original(url, **kw)
        if resposta is not None:
            return resposta
        try:
            r = requests.get(url, headers=UA_ALTERNATIVO, timeout=coletar_site.TIMEOUT, **kw)
            return r if r.status_code == 200 else None
        except requests.RequestException:
            return None
    return _get


def _coletar(base, limite):
    """Mesma ordem do coletar_site.coletar, mas para na primeira sonda com itens.

    O coletar() roda as quatro sondas sempre: no fise.com.br o wordpress_cpt
    (200 posts com _embed) leva 25 s e 726 MB mesmo com o WooCommerce ja tendo
    achado 100 produtos, e a funcao morre por memoria. E um achado vazio do
    sitemap ("sitemap", []) impedia o fallback da home.
    """
    import re as _re
    import coletar_site
    if not getattr(coletar_site, "_retentativa", False):
        coletar_site._get = _get_com_retentativa(coletar_site._get)
        coletar_site._retentativa = True
    home = coletar_site._get(base)
    plataforma, itens = "nenhuma", []
    sondas = (coletar_site.shopify, coletar_site.woocommerce, coletar_site.vtex,
              coletar_site.wordpress_cpt, lambda b: coletar_site.sitemap_generico(b, limite),
              lambda b: coletar_site.imagens_home(b, home))
    for sonda in sondas:
        try:
            achado = sonda(base)
        except Exception as erro:
            evento("extracao", f"sonda falhou: {type(erro).__name__}: {erro}", "aviso")
            achado = None
        if achado and achado[1]:
            plataforma, itens = achado
            break
    gerador = ""
    if home is not None:
        m = _re.search(r'<meta name="generator" content="([^"]+)"', home.text)
        gerador = m.group(1) if m else ""
    return {"site": base, "gerador": gerador, "plataforma": plataforma,
            "total": len(itens), "itens": itens[:limite]}


def coletar_candidatos(site):
    coleta = _coletar(normalizar_site(site), MAXIMO_CANDIDATOS)
    candidatos = [{"nome": i.get("nome") or "", "url": i.get("url") or "",
                   "imagem": i.get("imagem") or "", "preco": i.get("preco"),
                   "categoria": i.get("categoria") or "",
                   "descricao": i.get("descricao") or "", "origem": "site"}
                  for i in coleta.get("itens") or []]
    evento("extracao", f"site: {len(candidatos)} candidatos ({coleta.get('plataforma')})")
    return coleta, candidatos


def buscar_candidatos(cliente, segmento, limite=24):
    import extracao
    urls = []
    for consulta in (f'"{cliente}" produtos', f'"{cliente}" {segmento or ""} catálogo'):
        for url in extracao._search_web(consulta.strip(), 10):
            if url not in urls:
                urls.append(url)
    with ThreadPoolExecutor(8) as pool:
        registros = list(pool.map(_ler_pagina, urls[:limite]))
    achados = [{"nome": r["name"], "url": r["url"], "imagem": r["image"], "preco": r.get("price"),
                "categoria": r.get("category") or "", "descricao": r.get("description") or "",
                "origem": "busca"} for r in registros if r]
    evento("extracao", f"busca na web: {len(achados)} candidatos lidos página a página")
    return achados


def _ler_pagina(url):
    import extracao
    try:
        return extracao._record_from_page(url)
    except Exception:
        return None


def filtrar_candidatos(candidatos):
    """(validos, descartes). Toda imagem restante passa pelo verificar_imagens.py."""
    import verificar_imagens
    descartes, vistos, antes = [], set(), []
    for c in candidatos:
        motivo = None
        if not str(c.get("url") or "").startswith(("http://", "https://")):
            motivo = "sem URL de origem"
        elif not str(c.get("imagem") or "").startswith(("http://", "https://")):
            motivo = "sem imagem da fonte"
        elif not nome_valido(c.get("nome"), c["url"]):
            motivo = "nome não parece produto"
        elif IMAGEM_NAO_E_PRODUTO.search(c["imagem"]):
            motivo = "imagem de banner, ícone ou carrossel"
        elif sem_acento(c["nome"]) in vistos or c["imagem"] in vistos:
            motivo = "duplicado"
        if motivo:
            descartes.append({"nome": c.get("nome"), "motivo": motivo})
            continue
        vistos.update({sem_acento(c["nome"]), c["imagem"]})
        antes.append(c)
    with ThreadPoolExecutor(12) as pool:
        laudos = list(pool.map(verificar_imagens.conferir, [(c["nome"], c["imagem"]) for c in antes]))
    validos = []
    for c, (_, _, ok, detalhe) in zip(antes, laudos):
        if ok:
            validos.append(dict(c, imagem_laudo=detalhe))
        else:
            descartes.append({"nome": c["nome"], "motivo": f"imagem reprovada: {detalhe}"})
    return validos, descartes


INSTRUCAO_SELECAO = """Você monta o catálogo de demonstração de um portal B2B para o cliente abaixo.
Recebe uma lista NUMERADA de candidatos coletados do site do cliente e de buscas na web,
e as imagens dos primeiros candidatos.

Cliente: {cliente}
Site: {site}
Segmento informado: {segmento}

Regras obrigatórias:
- Escolha SOMENTE pelos números da lista. Nunca invente produto, nome, imagem ou preço.
- Descarte o que não é produto vendável: banner, slide de carrossel, seta de navegação,
  ícone, logo, foto institucional, foto de ambiente, categoria genérica, contato, blog.
  Exemplos que NÃO são produto: "biscoito2" (slide do carrossel), "previous arrow".
- Olhe a imagem: se ela for banner com texto promocional, arte de carrossel, ícone ou
  foto de ambiente, descarte mesmo que o nome pareça produto.
- Prefira produtos da marca/catálogo do próprio cliente. Candidato [busca] que não é do
  cliente só entra se o site não tiver produtos suficientes; marque "do_cliente": false.
- Escolha de {minimo} a {maximo} produtos, variados, em exatamente 3 categorias com nomes
  curtos em português.
- Se não houver ao menos {minimo} produtos reais, devolva "selecionados": [].
- Diga o segmento do cliente em poucas palavras.

Responda SOMENTE JSON:
{{"segmento": "...", "categorias": ["A", "B", "C"],
  "selecionados": [{{"n": 3, "categoria": 0, "do_cliente": true}}],
  "descartados_como_nao_produto": [7, 9]}}

Candidatos:
{lista}"""


def _chamar_openrouter(mensagens):
    import requests
    chave = os.environ.get("OPENROUTER_API_KEY")
    if not chave:
        raise RuntimeError("OPENROUTER_API_KEY não cadastrada na função da pipeline")
    resposta = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
        json={"model": MODELO_SELECAO, "messages": mensagens, "temperature": 0,
              "max_tokens": MAXIMO_TOKENS_SAIDA,
              "response_format": {"type": "json_object"}, "usage": {"include": True}},
        timeout=180)
    if resposta.status_code != 200:
        raise RuntimeError(f"OpenRouter HTTP {resposta.status_code}: {resposta.text[:300]}")
    corpo = resposta.json()
    texto = corpo["choices"][0]["message"]["content"] or ""
    texto = re.sub(r"^```(?:json)?|```$", "", texto.strip()).strip()
    uso = corpo.get("usage") or {}
    return json.loads(texto), {"modelo": corpo.get("model") or MODELO_SELECAO,
                               "custo_usd": uso.get("cost") or 0.0,
                               "tokens_entrada": uso.get("prompt_tokens") or 0,
                               "tokens_saida": uso.get("completion_tokens") or 0}


def selecionar(candidatos, cliente, site, segmento):
    linhas = []
    for n, c in enumerate(candidatos):
        arquivo = c["imagem"].split("?")[0].rsplit("/", 1)[-1][:60]
        linhas.append(f"{n}. [{c['origem']}] {c['nome'][:110]} | categoria: {c.get('categoria') or '-'}"
                      f" | url: {c['url'][:120]} | imagem: {arquivo}"
                      f" | {(c.get('descricao') or '')[:140]}")
    texto = INSTRUCAO_SELECAO.format(cliente=cliente, site=site, segmento=segmento or "não informado",
                                     minimo=MINIMO_PRODUTOS, maximo=MAXIMO_PRODUTOS,
                                     lista="\n".join(linhas))
    conteudo = [{"type": "text", "text": texto}]
    for n, c in enumerate(candidatos[:MAXIMO_IMAGENS_NO_PROMPT]):
        conteudo += [{"type": "text", "text": f"Imagem do candidato {n}:"},
                     {"type": "image_url", "image_url": {"url": c["imagem"]}}]
    try:
        escolha, custo = _chamar_openrouter([{"role": "user", "content": conteudo}])
        custo["com_imagens"] = True
    except (RuntimeError, ValueError) as erro:
        if "OPENROUTER_API_KEY" in str(erro) or "HTTP 402" in str(erro):
            raise
        evento("extracao", f"chamada com imagens falhou ({erro}); repetindo só com texto", "aviso")
        escolha, custo = _chamar_openrouter([{"role": "user", "content": texto}])
        custo["com_imagens"] = False
    return escolha, custo


def montar_pela_selecao(coleta, candidatos, escolha, cliente, segmento, descricao):
    """(catalogo, precos, situacao_preco, produtos_similares, regra_preco).

    Preco nunca vem do modelo: `montar_poc` usa o preco lido na pagina ou, sem
    ele, um estimado marcado com `_preco_estimado`.
    """
    import montar_poc
    categorias = [str(c).strip()[:60] for c in (escolha.get("categorias") or []) if str(c).strip()][:3]
    if len(categorias) < 3:
        categorias += ["Produtos em Destaque", "Linha Completa", "Lançamentos"][len(categorias):]
    itens, usados, do_cliente = [], set(), {}
    for s in escolha.get("selecionados") or []:
        try:
            n, ci = int(s.get("n")), int(s.get("categoria", 0))
        except (TypeError, ValueError):
            continue
        if not 0 <= n < len(candidatos) or n in usados:
            continue
        usados.add(n)
        itens.append((n, ci if 0 <= ci < 3 else 0))
        do_cliente[n] = s.get("do_cliente") is not False
    itens = itens[:MAXIMO_PRODUTOS]
    if len(itens) < MINIMO_PRODUTOS:
        raise PrecisaCatalogo(
            f"só {len(itens)} produtos reais com URL de origem e imagem válida "
            f"(mínimo {MINIMO_PRODUTOS}); mande o catálogo em PDF ou planilha")
    coleta_montagem = {"site": coleta.get("site"), "plataforma": coleta.get("plataforma"),
                       "itens": [{"nome": c["nome"], "preco": c["preco"] if _tem_preco(c) else None,
                                  "categoria": c["categoria"], "imagem": c["imagem"], "url": c["url"],
                                  "descricao": c.get("descricao") or ""} for c in candidatos]}
    catalogo = montar_poc.montar(coleta_montagem, cliente, (segmento or "Comércio B2B")[:120],
                                 descricao or f"{cliente} — catálogo B2B", categorias, itens)
    requisicoes = next(e for e in catalogo["etapas"] if e.get("endpoint") == "products")["requests"]
    precos = []
    for req, (n, _) in zip(requisicoes, itens):
        c = candidatos[n]
        req["_origem_url"] = c["url"]
        precos.append({"sku": req["payload"]["sku"], "nome": req["payload"]["name"],
                       "preco": req["payload"]["price"], "origem_url": c["url"],
                       "imagem": c["imagem"], "fonte": c["origem"],
                       "do_cliente": do_cliente[n],
                       "origem": "estimado" if req.get("_preco_estimado") else "publico"})
    return (catalogo, precos, situacao_preco(precos), not all(do_cliente[n] for n, _ in itens),
            regra_preco_estimado(candidatos, itens, precos))


def regra_preco_estimado(candidatos, itens, precos):
    """Descreve a regra fixa do montar_poc.py que deu o valor dos estimados.

    montar_poc: estimado = mediana dos precos publicos lidos nas paginas dos
    produtos escolhidos; sem nenhum, R$ 100,00 fixo. O modelo nunca entra aqui.
    """
    estimados = [p for p in precos if p["origem"] == "estimado"]
    if not estimados:
        return None
    publicos = [candidatos[n]["preco"] for n, _ in itens if _tem_preco(candidatos[n])]
    valor = f"R$ {estimados[0]['preco']:.2f}".replace(".", ",")
    if publicos:
        return (f"preço estimado = mediana dos {len(publicos)} preços públicos lidos no mesmo site "
                f"({valor}), regra fixa do montar_poc.py")
    return (f"preço estimado = valor fixo {valor} do montar_poc.py: nenhum produto escolhido "
            f"tem preço público na página")


def _tem_preco(candidato):
    return isinstance(candidato.get("preco"), (int, float)) and candidato["preco"] > 0


def situacao_preco(precos):
    """Bate com o catalogo: ausente so sem produto precificado (ENTREGA.md)."""
    if not precos or not any(p.get("preco") for p in precos):
        return "ausente"
    return "publico" if all(p["origem"] == "publico" for p in precos) else "estimado"

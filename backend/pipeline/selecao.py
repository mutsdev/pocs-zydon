"""Extracao por IA restrita a candidatos coletados.

O modelo so ESCOLHE entre candidatos com URL de origem e imagem da mesma fonte.
Nome, URL, imagem e preco saem sempre do candidato; do modelo saem apenas os
indices, a categoria e o julgamento "e da marca do cliente?". Modelo fixado por
id exato (nunca alias "latest").
"""

import hashlib
import html
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

MODELO_SELECAO = "gemini-3.5-flash-lite"
MODELOS_RESERVA = ("gemini-3.1-flash-lite", "gemini-3.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
CONFERENCIA_POR_CHAMADA = 20
MODELO_OPENROUTER = "google/gemini-2.5-flash"
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


class SemCreditoOpenRouter(RuntimeError):
    """Cota do modelo esgotada (HTTP 402/429): a selecao nao pode rodar agora."""


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


def palavras_do_foco(foco):
    """(incluir, excluir): radicais antes e depois de "não"/"sem" ("peças, não a bicicleta")."""
    partes = re.split(r"(?i)\bn[aã]o\b|\bsem\b|\bexceto\b", foco or "", maxsplit=1)

    def radicais(texto):
        return {sem_acento(p)[:6] for p in re.findall(r"[A-Za-zÀ-ú]{4,}", texto or "")
                if sem_acento(p) not in PALAVRAS_VAZIAS and sem_acento(p) not in {"completa", "completo", "inteira"}}
    return radicais(partes[0]), radicais(partes[1] if len(partes) > 1 else "")


def ordenar_pelo_foco(urls, foco):
    """Endereços do tipo pedido primeiro, os excluídos por último (ordem estável)."""
    incluir, excluir = palavras_do_foco(foco)
    if not incluir and not excluir:
        return urls

    def nota(url):
        slug = sem_acento(url)
        return (-2 if any(r in slug for r in excluir) else 0) + (1 if any(r in slug for r in incluir) else 0)
    return sorted(urls, key=nota, reverse=True)


def _coletar(base, limite, foco=""):
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
              coletar_site.wordpress_cpt, lambda b: _sitemap_pelo_foco(coletar_site, b, limite, foco),
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


def _sitemap_pelo_foco(coletar_site, base, limite, foco):
    if not foco:
        return coletar_site.sitemap_generico(base, limite)
    urls = coletar_site._urls_sitemap(base, 2000)
    if not urls:
        return None
    urls = ordenar_pelo_foco(urls, foco)[:limite]
    with ThreadPoolExecutor(8) as ex:
        itens = [i for i in ex.map(coletar_site._pagina_produto, urls) if i and i["imagem"]]
    evento("extracao", f"sitemap: {len(urls)} endereços lidos, os do foco primeiro")
    return "sitemap", itens


def limpar_texto(texto):
    """Entidades HTML decodificadas ("&amp;" -> "&") e espacos normalizados."""
    texto = str(texto or "")
    for _ in range(2):
        texto = html.unescape(texto)
    return re.sub(r"\s+", " ", texto).strip()


def candidato(nome, url, imagem, preco, categoria, descricao, origem):
    return {"nome": limpar_texto(nome), "url": url or "", "imagem": imagem or "", "preco": preco,
            "categoria": limpar_texto(categoria), "descricao": limpar_texto(descricao),
            "origem": origem}


PAGINA_NAO_E_SECAO = re.compile(
    r"contato|quem-?somos|sobre|politica|privacidade|blog|noticia|trabalhe|login|carrinho|conta|faq", re.I)


def _imagem_cheia(src):
    """Wix serve miniatura borrada (/v1/fill/w_49,...,blur_2); a original e o /media/<id>."""
    m = re.match(r"(https?://static\.wixstatic\.com/media/[^/]+?\.(?:png|jpe?g|webp))", src or "", re.I)
    return m.group(1) if m else src


def coletar_secoes(base, limite=60):
    """Site institucional com uma pagina por linha de produto (Master Foods Mix, Wix):
    cada produto e um titulo (h3/h4) colado numa imagem. A imagem tem nome de
    arquivo ("ChatGPT Image 4 de mar...") como alt, entao o nome vem do titulo."""
    import requests
    from bs4 import BeautifulSoup
    cabecalho = {"User-Agent": "Mozilla/5.0"}
    try:
        home = requests.get(base, headers=cabecalho, timeout=20)
    except requests.RequestException:
        return []
    host = urlparse(base).hostname
    links = []
    for a in BeautifulSoup(home.text, "html.parser").find_all("a", href=True):
        url = urljoin(base, a["href"]).split("#")[0].split("?")[0].rstrip("/")
        partes = [p for p in urlparse(url).path.split("/") if p]
        if (urlparse(url).hostname == host and len(partes) == 1 and url not in links
                and not PAGINA_NAO_E_SECAO.search(partes[0])):
            links.append(url)
    itens = []
    for url in links[:10]:
        try:
            pagina = requests.get(url, headers=cabecalho, timeout=20).text
        except requests.RequestException:
            continue
        sopa = BeautifulSoup(pagina, "html.parser")
        for lixo in sopa(["script", "style", "noscript"]):
            lixo.decompose()
        titulo_secao = sopa.find(["h1", "h2"])
        secao = limpar_texto(titulo_secao.get_text(" ", strip=True)) if titulo_secao else ""
        imagem_pendente = None
        for el in sopa.find_all(["img", "h3", "h4"]):
            if el.name == "img":
                src = _imagem_cheia(el.get("src") or el.get("data-src") or "")
                imagem_pendente = src if src.startswith("http") else None
                continue
            nome = limpar_texto(el.get_text(" ", strip=True))
            if imagem_pendente and 3 < len(nome) < 90:
                itens.append(candidato(nome, url, imagem_pendente, None, secao, "", "site"))
            imagem_pendente = None
        if len(itens) >= limite:
            break
    evento("extracao", f"páginas de seção: {len(itens)} candidatos em {min(len(links), 10)} páginas")
    return itens[:limite]


def coletar_candidatos(site, foco=""):
    coleta = _coletar(normalizar_site(site), MAXIMO_CANDIDATOS, foco)
    candidatos = [candidato(i.get("nome"), i.get("url"), i.get("imagem"), i.get("preco"),
                            i.get("categoria"), i.get("descricao"), "site")
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
    achados = [candidato(r["name"], r["url"], r["image"], r.get("price"), r.get("category"),
                         r.get("description"), "busca") for r in registros if r]
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
        if not str(c.get("url") or "").startswith(("http://", "https://", "anexo:")):
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
e as imagens dos primeiros candidatos. Todos já passaram por um filtro de URL e imagem.

Cliente: {cliente}
Site: {site}
Segmento informado: {segmento}
Foco do pedido (tipo de produto que o usuário quer no portal): {foco}

Regras obrigatórias:
- Escolha SOMENTE pelos números da lista. Nunca invente produto, nome, imagem ou preço.
- Quantidade: escolha EXATAMENTE {alvo} produtos (há {total} candidatos). Só escolha menos se
  não houver {alvo} produtos reais; nesse caso explique cada descarte.
- Descarte o que não é produto vendável: banner, slide de carrossel, seta de navegação,
  ícone, logo, foto institucional, foto de ambiente, depoimento de cliente, nome de
  categoria ou menu ("CERAS", "PNEUS"), contato, blog.
  Exemplos que NÃO são produto: "biscoito2" (slide do carrossel), "previous arrow".
- Olhe a imagem: banner com texto promocional, arte de carrossel, ícone ou foto de
  ambiente é descarte, mesmo que o nome pareça produto.
- Priorize produtos da marca/catálogo do próprio cliente. Candidato [busca] que não é do
  cliente só entra se faltar produto do site; marque "do_cliente": false.
- Espalhe a escolha entre as categorias do site (campo "categoria" dos candidatos): pegue
  de todas antes de repetir a mesma. Não escolha dois tamanhos do mesmo produto se houver
  outro produto disponível.
- Agrupe os escolhidos em exatamente 3 categorias com nomes curtos em português; use os
  nomes das categorias do site quando existirem.
- Para CADA candidato não escolhido, devolva o número e o motivo em uma frase curta, com
  o tipo: "nao_e_produto", "outra_marca", "repetido" (variação/tamanho de um escolhido)
  ou "limite" (produto bom que ficou de fora pela quantidade ou pela variedade).
- Se há foco do pedido, escolha PRIMEIRO os candidatos que são desse tipo de produto e
  descarte com tipo "fora_do_foco" os que não são (ex.: foco "peças, não a bicicleta":
  bicicleta completa é "fora_do_foco"). Só complete com fora do foco se faltar produto.
- Diga o segmento do cliente pelo que ele VENDE, em 2 a 5 palavras, específico
  (ex.: "bicicletas e peças", "abrasivos e discos de corte", "biscoitos e salgadinhos").
- Em cada escolhido, "no_foco": true se ele é do tipo pedido no foco, false se não é
  (sem foco, sempre true).
  Nunca responda algo genérico como "distribuição B2B", "comércio" ou "varejo".

Responda SOMENTE JSON:
{{"segmento": "...", "categorias": ["A", "B", "C"],
  "selecionados": [{{"n": 3, "categoria": 0, "do_cliente": true, "no_foco": true}}],
  "descartados": [{{"n": 7, "tipo": "nao_e_produto", "motivo": "slide do carrossel"}}]}}

Candidatos:
{lista}"""


def _chamar_openrouter_pago(mensagens):
    import requests
    chave = os.environ.get("OPENROUTER_API_KEY")
    if not chave:
        raise RuntimeError("OPENROUTER_API_KEY não cadastrada na função da pipeline")
    resposta = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
        json={"model": MODELO_OPENROUTER, "messages": mensagens, "temperature": 0,
              "max_tokens": MAXIMO_TOKENS_SAIDA,
              "response_format": {"type": "json_object"}, "usage": {"include": True}},
        timeout=180)
    if resposta.status_code == 402:
        raise SemCreditoOpenRouter(
            "OpenRouter sem crédito (HTTP 402): a conta não tem saldo para a seleção dos produtos. "
            "Ponha crédito em openrouter.ai/settings/credits e reenvie o pedido. "
            f"Resposta: {resposta.text[:200]}")
    if resposta.status_code != 200:
        raise RuntimeError(f"OpenRouter HTTP {resposta.status_code}: {resposta.text[:300]}")
    corpo = resposta.json()
    texto = corpo["choices"][0]["message"]["content"] or ""
    texto = re.sub(r"^```(?:json)?|```$", "", texto.strip()).strip()
    uso = corpo.get("usage") or {}
    return json.loads(texto), {"modelo": corpo.get("model") or MODELO_OPENROUTER,
                               "custo_usd": uso.get("cost") or 0.0,
                               "tokens_entrada": uso.get("prompt_tokens") or 0,
                               "tokens_saida": uso.get("completion_tokens") or 0}


def _imagem_inline(url):
    """Baixa a imagem e devolve (mime, base64) reduzida a 512 px; None se falhar."""
    import base64
    import io
    import requests
    from PIL import Image
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                   "AppleWebKit/537.36 Chrome/128.0 Safari/537.36"})
        if r.status_code != 200:
            return None
        imagem = Image.open(io.BytesIO(r.content)).convert("RGB")
        imagem.thumbnail((512, 512))
        saida = io.BytesIO()
        imagem.save(saida, "JPEG", quality=80)
        return "image/jpeg", base64.b64encode(saida.getvalue()).decode()
    except Exception:
        return None


def _chamar_openrouter(mensagens):
    """Chama o Gemini (plano gratuito) com o mesmo formato de mensagens de antes.
    Imagens por URL sao baixadas e enviadas inline; a que nao baixa vira texto."""
    import requests
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        return _chamar_openrouter_pago(mensagens)
    partes = []
    for mensagem in mensagens:
        conteudo = mensagem["content"]
        if isinstance(conteudo, str):
            partes.append({"text": conteudo})
            continue
        urls = [c["image_url"]["url"] for c in conteudo if c.get("type") == "image_url"]
        with ThreadPoolExecutor(8) as pool:
            baixadas = dict(zip(urls, pool.map(_imagem_inline, urls)))
        for c in conteudo:
            if c.get("type") == "text":
                partes.append({"text": c["text"]})
            elif baixadas.get(c["image_url"]["url"]):
                mime, dados = baixadas[c["image_url"]["url"]]
                partes.append({"inline_data": {"mime_type": mime, "data": dados}})
            else:
                partes.append({"text": "(imagem não pôde ser baixada)"})
    corpo_pedido = {"contents": [{"role": "user", "parts": partes}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": MAXIMO_TOKENS_SAIDA,
                                         "responseMimeType": "application/json"}}
    import time
    resposta, modelo_usado = None, MODELO_SELECAO
    for modelo_usado in (MODELO_SELECAO,) + MODELOS_RESERVA:
        for tentativa in range(2):
            try:
                resposta = requests.post(GEMINI_URL.format(modelo=modelo_usado), json=corpo_pedido,
                                         headers={"x-goog-api-key": chave}, timeout=90)
            except requests.RequestException as erro:
                evento("extracao", f"{modelo_usado} sem resposta ({type(erro).__name__})", "aviso")
                resposta = None
                continue
            if resposta.status_code not in (429, 500, 503):
                break
            time.sleep(8)
        if resposta is not None and resposta.status_code not in (429, 500, 503):
            break
        evento("extracao", f"{modelo_usado} ocupado; tentando o modelo reserva", "aviso")
    if resposta is None:
        raise RuntimeError("Gemini sem resposta em nenhum dos modelos")
    if resposta.status_code in (402, 429):
        raise SemCreditoOpenRouter(
            f"cota gratuita do Gemini esgotada (HTTP {resposta.status_code}): o modelo não pôde "
            "escolher nem conferir os produtos agora. Reenvie o pedido mais tarde. "
            f"Resposta: {resposta.text[:200]}")
    if resposta.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {resposta.status_code}: {resposta.text[:300]}")
    corpo = resposta.json()
    candidato_resposta = (corpo.get("candidates") or [{}])[0]
    texto = "".join(p.get("text", "") for p in (candidato_resposta.get("content") or {}).get("parts") or []
                    if not p.get("thought"))
    texto = re.sub(r"^```(?:json)?|```$", "", texto.strip()).strip()
    uso = corpo.get("usageMetadata") or {}
    return json.loads(texto), {"modelo": modelo_usado, "custo_usd": 0.0,
                               "tokens_entrada": uso.get("promptTokenCount") or 0,
                               "tokens_saida": (uso.get("candidatesTokenCount") or 0)
                               + (uso.get("thoughtsTokenCount") or 0)}


INSTRUCAO_CONFERIR_FOTO = """Você confere fotos de produtos de um catálogo B2B do cliente "{cliente}".
Para cada item abaixo há o NOME anunciado e a FOTO. Diga se a foto mostra de fato aquele produto
(o mesmo tipo de item do nome; embalagem do produto vale). NÃO confere quando a foto é: logo,
banner, slide de carrossel, seta, ícone, foto de loja/fachada/pessoas, texto sem produto, ou um
produto de outro tipo (ex.: nome diz "disco de corte" e a foto é uma bicicleta).
Não invente: descreva só o que aparece na foto.
Responda só JSON: {{"itens": [{{"n": 0, "confere": true, "o_que_aparece": "disco de desbaste amarelo"}}]}}

Itens:
{lista}"""


def conferir_fotos(candidatos, cliente):
    """(aprovados, descartes, custo). O modelo olha cada foto e diz se é o produto do nome.
    Sem resposta para um item, ele passa (a conferência nunca inventa nem apaga em silêncio)."""
    custo = {"custo_usd": 0.0, "tokens_entrada": 0, "tokens_saida": 0}
    aprovados, descartes = [], []
    for inicio in range(0, len(candidatos), CONFERENCIA_POR_CHAMADA):
        lote = candidatos[inicio:inicio + CONFERENCIA_POR_CHAMADA]
        lista = "\n".join(f"{n}. {c['nome'][:110]}" for n, c in enumerate(lote))
        conteudo = [{"type": "text", "text": INSTRUCAO_CONFERIR_FOTO.format(cliente=cliente, lista=lista)}]
        for n, c in enumerate(lote):
            conteudo += [{"type": "text", "text": f"Foto do item {n} ({c['nome'][:80]}):"},
                         {"type": "image_url", "image_url": {"url": c["imagem"]}}]
        try:
            resposta, custo_lote = _chamar_openrouter([{"role": "user", "content": conteudo}])
        except SemCreditoOpenRouter:
            raise
        except Exception as erro:
            evento("extracao", f"conferência das fotos falhou ({erro}); itens seguem sem conferência", "aviso")
            aprovados += [dict(c, foto_conferida=False) for c in lote]
            continue
        for k in custo:
            custo[k] += custo_lote.get(k) or 0
        laudos = {}
        for item in resposta.get("itens") or []:
            try:
                laudos[int(item.get("n"))] = item
            except (TypeError, ValueError, AttributeError):
                continue
        for n, c in enumerate(lote):
            laudo = laudos.get(n)
            if laudo is None:
                aprovados.append(dict(c, foto_conferida=False))
            elif laudo.get("confere") is False:
                descartes.append({"nome": c["nome"], "tipo": "foto_errada",
                                  "motivo": "a foto não mostra o produto: "
                                  + limpar_texto(laudo.get("o_que_aparece") or "outro item")[:120]})
            else:
                aprovados.append(dict(c, foto_conferida=True,
                                      foto_mostra=limpar_texto(laudo.get("o_que_aparece") or "")[:120]))
    evento("extracao", f"fotos conferidas pelo modelo: {len(aprovados)} aprovadas, "
                       f"{len(descartes)} recusadas")
    return aprovados, descartes, custo


def selecionar(candidatos, cliente, site, segmento, foco=""):
    linhas = []
    for n, c in enumerate(candidatos):
        arquivo = c["imagem"].split("?")[0].rsplit("/", 1)[-1][:60]
        linhas.append(f"{n}. [{c['origem']}] {c['nome'][:110]} | categoria: {c.get('categoria') or '-'}"
                      f" | url: {c['url'][:120]} | imagem: {arquivo}"
                      f" | {(c.get('descricao') or '')[:140]}")
    texto = INSTRUCAO_SELECAO.format(cliente=cliente, site=site, segmento=segmento or "não informado",
                                     foco=foco or "nenhum (catálogo variado do cliente)",
                                     alvo=min(MAXIMO_PRODUTOS, len(candidatos)),
                                     total=len(candidatos), lista="\n".join(linhas))
    conteudo = [{"type": "text", "text": texto}]
    for n, c in enumerate(candidatos[:MAXIMO_IMAGENS_NO_PROMPT]):
        conteudo += [{"type": "text", "text": f"Imagem do candidato {n}:"},
                     {"type": "image_url", "image_url": {"url": c["imagem"]}}]
    try:
        escolha, custo = _chamar_openrouter([{"role": "user", "content": conteudo}])
        custo["com_imagens"] = True
    except SemCreditoOpenRouter:
        raise
    except (RuntimeError, ValueError) as erro:
        if "GEMINI_API_KEY" in str(erro):
            raise
        evento("extracao", f"chamada com imagens falhou ({erro}); repetindo só com texto", "aviso")
        escolha, custo = _chamar_openrouter([{"role": "user", "content": texto}])
        custo["com_imagens"] = False
    return escolha, custo


def ler_descartes(escolha, candidatos, usados):
    """{n: (tipo, motivo)} para cada candidato valido nao escolhido."""
    motivos = {}
    for d in escolha.get("descartados") or []:
        try:
            n = int(d.get("n"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= n < len(candidatos) and n not in usados:
            motivos[n] = (str(d.get("tipo") or "limite"), limpar_texto(d.get("motivo"))[:160])
    for n in range(len(candidatos)):
        if n not in usados and n not in motivos:
            motivos[n] = ("sem_motivo", "o modelo não escolheu nem explicou")
    return motivos


def completar_ate_o_alvo(itens, candidatos, motivos, categorias):
    """Com 12+ validos saem 12: completa com os 'limite' e 'sem_motivo', na ordem,
    alternando categoria do site para espalhar. Nunca com 'nao_e_produto'."""
    alvo = min(MAXIMO_PRODUTOS, len(candidatos))
    usados = {n for n, _ in itens}
    sobra = [n for n in range(len(candidatos)) if n not in usados
             and motivos.get(n, ("",))[0] in ("limite", "sem_motivo")]
    ja = {}
    for n, _ in itens:
        chave = sem_acento(candidatos[n]["categoria"])
        ja[chave] = ja.get(chave, 0) + 1
    completados = []
    while len(itens) < alvo and sobra:
        sobra.sort(key=lambda n: ja.get(sem_acento(candidatos[n]["categoria"]), 0))
        n = sobra.pop(0)
        chave = sem_acento(candidatos[n]["categoria"])
        ja[chave] = ja.get(chave, 0) + 1
        indice = next((i for i, c in enumerate(categorias)
                       if sem_acento(c) and sem_acento(c) in sem_acento(candidatos[n]["categoria"])), 0)
        itens.append((n, indice))
        completados.append(n)
    return completados


def montar_pela_selecao(coleta, candidatos, escolha, cliente, segmento, descricao):
    """(catalogo, precos, situacao_preco, produtos_similares, regra_preco, descartes_modelo).

    Preco nunca vem do modelo: preco lido na pagina; sem ele, a mediana dos
    publicos do mesmo site (montar_poc) ou a faixa fixa de faixas_preco.json.
    """
    import montar_poc
    categorias = [limpar_texto(c)[:60] for c in (escolha.get("categorias") or []) if str(c).strip()][:3]
    if len(categorias) < 3:
        categorias += ["Produtos em Destaque", "Linha Completa", "Lançamentos"][len(categorias):]
    itens, usados, do_cliente, fora_do_foco = [], set(), {}, set()
    for s in escolha.get("selecionados") or []:
        try:
            n, ci = int(s.get("n")), int(s.get("categoria", 0))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 0 <= n < len(candidatos) or n in usados:
            continue
        usados.add(n)
        itens.append((n, ci if 0 <= ci < 3 else 0))
        do_cliente[n] = s.get("do_cliente") is not False
        if s.get("no_foco") is False:
            fora_do_foco.add(n)
    itens = itens[:MAXIMO_PRODUTOS]
    motivos = ler_descartes(escolha, candidatos, usados)
    completados = completar_ate_o_alvo(itens, candidatos, motivos, categorias)
    for n in completados:
        do_cliente[n] = candidatos[n]["origem"] in ("site", "anexo")
        motivos.pop(n, None)
    descartes_modelo = [{"nome": candidatos[n]["nome"], "tipo": tipo, "motivo": f"modelo: {motivo}"}
                        for n, (tipo, motivo) in sorted(motivos.items())]
    if len(itens) < MINIMO_PRODUTOS:
        raise PrecisaCatalogo(
            f"só {len(itens)} produtos reais com URL de origem e imagem válida "
            f"(mínimo {MINIMO_PRODUTOS}); mande o catálogo em PDF ou planilha",
            {"descartes_modelo": descartes_modelo})
    coleta_montagem = {"site": coleta.get("site"), "plataforma": coleta.get("plataforma"),
                       "itens": [{"nome": c["nome"], "preco": c["preco"] if _tem_preco(c) else None,
                                  "categoria": c["categoria"], "imagem": c["imagem"], "url": c["url"],
                                  "descricao": c.get("descricao") or ""} for c in candidatos]}
    catalogo = montar_poc.montar(coleta_montagem, cliente, (segmento or "Comércio B2B")[:120],
                                 descricao or f"{cliente} — catálogo B2B", categorias, itens)
    requisicoes = next(e for e in catalogo["etapas"] if e.get("endpoint") == "products")["requests"]
    publicos = [candidatos[n]["preco"] for n, _ in itens if _tem_preco(candidatos[n])]
    faixas = FaixasPreco.carregar()
    segmento_faixa = faixas.segmento(segmento, [candidatos[n]["nome"] for n, _ in itens])
    precos, regras = [], set()
    for req, (n, ci) in zip(requisicoes, itens):
        c = candidatos[n]
        req["_origem_url"] = c["url"]
        if c.get("file_id"):
            req["_file_id"] = c["file_id"]
        if c.get("miniatura"):
            req["_miniatura"] = c["miniatura"]
        entrada = {"sku": req["payload"]["sku"], "nome": req["payload"]["name"],
                   "origem_url": c["url"], "imagem": c["imagem"], "fonte": c["origem"],
                   "do_cliente": do_cliente[n], "completado": n in completados,
                   "nome_lido_na_imagem": bool(c.get("nome_lido_na_imagem"))}
        if not req.get("_preco_estimado"):
            entrada.update(origem="publico", regra=("lido no anexo do cliente" if c["origem"] == "anexo"
                                                   else "lido na página do produto"))
        elif publicos:
            entrada.update(origem="estimado",
                           regra=f"mediana dos {len(publicos)} preços públicos do mesmo site")
        else:
            valor, regra = faixas.sortear(segmento_faixa, c["nome"],
                                          " ".join([c["categoria"], categorias[ci], c["nome"]]))
            req["payload"]["price"] = valor
            for variacao in req["payload"].get("variations") or []:
                variacao["price"] = valor
            entrada.update(origem="estimado", regra=regra)
        entrada["preco"] = req["payload"]["price"]
        if entrada["origem"] == "estimado":
            regras.add(entrada["regra"])
        precos.append(entrada)
    regra_preco = None
    if regras:
        regra_preco = ("preço estimado por regra fixa, nunca pelo modelo: "
                       + "; ".join(sorted(regras))
                       + (f" (tabela faixas_preco.json v{faixas.versao})" if not publicos else ""))
    descartes_modelo.append({"_fora_do_foco": sum(1 for n, _ in itens if n in fora_do_foco)})
    return (catalogo, precos, situacao_preco(precos), not all(do_cliente[n] for n, _ in itens),
            regra_preco, descartes_modelo)


class FaixasPreco:
    """Tabela versionada de faixas por segmento e categoria (faixas_preco.json)."""

    def __init__(self, dados):
        self.dados, self.versao = dados, dados.get("versao")

    @classmethod
    def carregar(cls):
        candidatos = [Path(os.environ.get("ZYDON_REPO", "")) / "Criar Portais" / "faixas_preco.json",
                      Path(__file__).with_name("faixas_preco.json")]
        for caminho in candidatos:
            if caminho.is_file():
                return cls(json.loads(caminho.read_text(encoding="utf-8")))
        raise RuntimeError("faixas_preco.json não encontrado")

    @staticmethod
    def _pontos(texto, radicais):
        base = sem_acento(texto)
        palavras = re.findall(r"[a-z0-9]+", base)
        return sum(1 for r in radicais if any(p.startswith(r) for p in palavras))

    def segmento(self, segmento, nomes):
        texto_segmento = segmento or ""
        melhor, pontos = None, 0
        for s in self.dados["segmentos"]:
            p = 3 * self._pontos(texto_segmento, s["radicais"]) + self._pontos(" ".join(nomes), s["radicais"])
            if p > pontos:
                melhor, pontos = s, p
        return melhor

    def sortear(self, segmento, nome, contexto):
        """(valor, regra). Semente = sha256 do nome normalizado: sempre o mesmo valor."""
        faixa, origem = self.dados["padrao"]["faixa"], f"faixa padrão ({self.dados['padrao']['nome']})"
        if segmento:
            faixa, origem = segmento["faixa"], f"faixa do segmento {segmento['nome']}"
            melhor, pontos = None, 0
            for cat in segmento.get("categorias") or []:
                p = self._pontos(contexto, cat["radicais"])
                if p > pontos:
                    melhor, pontos = cat, p
            if melhor:
                faixa, origem = melhor["faixa"], f"faixa {segmento['nome']} / {melhor['nome']}"
        semente = int(hashlib.sha256(sem_acento(nome).encode("utf-8")).hexdigest()[:12], 16)
        fracao = semente / float(16 ** 12)
        baixo, alto = float(faixa[0]), float(faixa[1])
        valor = int(baixo + fracao * (alto - baixo)) + float(self.dados.get("centavos", 0.9))
        valor = round(min(max(valor, baixo), alto + 1), 2)
        texto = f"R$ {baixo:.2f}–{alto:.2f}".replace(".", ",")
        return valor, f"sorteio com semente no nome dentro da {origem} ({texto})"


def _tem_preco(candidato):
    return isinstance(candidato.get("preco"), (int, float)) and candidato["preco"] > 0


def situacao_preco(precos):
    """Bate com o catalogo: ausente so sem produto precificado (ENTREGA.md)."""
    if not precos or not any(p.get("preco") for p in precos):
        return "ausente"
    return "publico" if all(p["origem"] == "publico" for p in precos) else "estimado"


NOME_DE_ARQUIVO = re.compile(r"^[\w\-. ]*\d{5,}[\w\-. ]*$|^(img|image|foto|dsc|whatsapp)[\w\-. ]*$", re.I)
SECAO_INSTITUCIONAL = re.compile(
    r"depoiment|avalia|quem|sobre|contato|encontre|pergunta|copyright|diferencia|endere", re.I)


def coletar_fotos_sem_nome(base, limite=24):
    """Fotos de produto sem nome útil (Acqua & Corte: carrossel "Linha de Discos
    Diamantados" com fotos do Instagram "5555..._n.jpg"). Categoria = o título da
    seção (h2) acima da foto. O nome só entra se for LIDO NA IMAGEM (nomear_pela_imagem)."""
    import requests
    from bs4 import BeautifulSoup
    try:
        pagina = requests.get(base, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    except requests.RequestException:
        return []
    sopa = BeautifulSoup(pagina, "html.parser")
    secao, fotos, vistas = "", [], set()
    for el in sopa.find_all(["h2", "img"]):
        if el.name == "h2":
            titulo = limpar_texto(el.get_text(" ", strip=True))
            if len(titulo) <= 60 or not secao:
                secao = titulo[:80]
            continue
        src = el.get("data-src") or el.get("data-lazy-src") or el.get("src") or ""
        src = urljoin(base, src.strip())
        arquivo = src.split("?")[0].rsplit("/", 1)[-1]
        alt = limpar_texto(el.get("alt"))
        if (not src.startswith("http") or src in vistas or IMAGEM_NAO_E_PRODUTO.search(src)
                or not secao or SECAO_INSTITUCIONAL.search(secao)):
            continue
        if alt and not NOME_DE_ARQUIVO.match(alt) and nome_valido(alt, base):
            continue
        if not NOME_DE_ARQUIVO.match(arquivo.rsplit(".", 1)[0]):
            continue
        vistas.add(src)
        fotos.append(candidato("", base, src, None, secao, "", "site"))
    evento("extracao", f"fotos sem nome no site: {len(fotos)}")
    return fotos[:limite]


INSTRUCAO_NOME_NA_IMAGEM = """Cada imagem abaixo é uma foto do site do cliente {cliente}, na seção "{secao}".
Para cada uma, diga o NOME DO PRODUTO somente se ele estiver ESCRITO e legível na própria foto
(embalagem, rótulo, etiqueta, texto do produto). Nunca invente: se não houver texto legível
que nomeie o produto, devolva null. Foto de pessoa, ambiente, loja ou arte sem produto: null.
Responda SOMENTE JSON: {{"itens": [{{"n": 0, "nome": "Disco Diamantado Omega C2 Turbo" ou null}}]}}"""


def nomear_pela_imagem(fotos, cliente):
    """(candidatos nomeados, descartes, custo). O modelo só transcreve o texto da foto."""
    custo = {"custo_usd": 0.0, "tokens_entrada": 0, "tokens_saida": 0}
    if not fotos:
        return [], [], custo
    secao = fotos[0].get("categoria") or ""
    conteudo = [{"type": "text", "text": INSTRUCAO_NOME_NA_IMAGEM.format(cliente=cliente, secao=secao)}]
    for n, f in enumerate(fotos):
        conteudo += [{"type": "text", "text": f"Foto {n} (seção {f['categoria']}):"},
                     {"type": "image_url", "image_url": {"url": f["imagem"]}}]
    try:
        resposta, custo = _chamar_openrouter([{"role": "user", "content": conteudo}])
    except SemCreditoOpenRouter:
        raise
    except Exception as erro:
        evento("extracao", f"leitura do nome nas fotos falhou: {erro}", "aviso")
        return [], [{"nome": f["imagem"].rsplit("/", 1)[-1], "motivo": "foto sem nome e leitura falhou"}
                    for f in fotos], custo
    nomes = {}
    for item in resposta.get("itens") or []:
        try:
            nomes[int(item.get("n"))] = limpar_texto(item.get("nome") or "")
        except (TypeError, ValueError, AttributeError):
            continue
    nomeados, descartes = [], []
    for n, f in enumerate(fotos):
        nome = nomes.get(n) or ""
        if nome and nome.lower() != "null" and nome_valido(nome, f["url"]):
            nomeados.append(dict(f, nome=nome[:110], nome_lido_na_imagem=True,
                                 descricao=f"{nome} — nome lido na foto do site."))
        else:
            descartes.append({"nome": f["imagem"].rsplit("/", 1)[-1][:60],
                              "motivo": "foto sem nome legível na imagem"})
    evento("extracao", f"nomes lidos nas fotos: {len(nomeados)} de {len(fotos)}")
    return nomeados, descartes, custo


MARKETPLACES = re.compile(
    r"shopee|amazon\.|magazineluiza|magalu|americanas|aliexpress|"
    r"casasbahia|submarino|olx\.|wikipedia|youtube|facebook|instagram|letras\.mus|reclameaqui|"
    r"linkedin|tiktok|pinterest|google\.", re.I)
CAPTCHA = re.compile(r"confirme seu acesso|captcha|are you a robot|access denied", re.I)


def buscar_duckduckgo(consulta, limite=10):
    """URLs orgânicas do DuckDuckGo HTML (Google/Bing devolvem página de bloqueio)."""
    import requests
    from urllib.parse import parse_qs, unquote
    from bs4 import BeautifulSoup
    try:
        r = requests.get("https://html.duckduckgo.com/html/", params={"q": consulta, "kl": "br-pt"},
                         headers={"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                                 "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
                                  "Referer": "https://html.duckduckgo.com/"}, timeout=20)
    except requests.RequestException:
        return []
    if "anomaly" in r.text and "result__a" not in r.text:
        evento("extracao", "DuckDuckGo pediu verificação anti-robô; usando o Bing nesta busca", "aviso")
        return []
    urls = []
    for a in BeautifulSoup(r.text, "html.parser").select("a.result__a"):
        href = a.get("href") or ""
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        if "duckduckgo.com/y.js" in href or "/y.js?" in href:
            continue
        if href.startswith("http") and not MARKETPLACES.search(href) and href not in urls:
            urls.append(href)
    return urls[:limite]


MERCADO_LIVRE = re.compile(r"mercadoli[vb]re\.com", re.I)


def ler_mercado_livre(url):
    """O Mercado Livre manda o navegador comum para a verificação de conta; com o
    agente de prévia de link ele entrega og:title, og:image e o preço da página."""
    import requests
    from bs4 import BeautifulSoup
    try:
        r = requests.get(url, headers={"User-Agent": "facebookexternalhit/1.1"}, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    sopa = BeautifulSoup(r.text, "html.parser")

    def meta(nome):
        tag = sopa.find("meta", attrs={"property": nome}) or sopa.find("meta", attrs={"name": nome})
        return (tag.get("content") or "").strip() if tag else ""
    nome, imagem = meta("og:title"), meta("og:image")
    if not nome or not imagem or CAPTCHA.search(nome):
        return None
    nome = re.sub(r"\s*[|-]\s*Mercado Livre.*$", "", nome).strip()
    nome = re.sub(r"\s+-\s+R\$\s*[\d.,]+\s*$", "", nome).strip()
    preco = None
    achado = re.search(r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)', r.text)
    if achado:
        preco = float(achado.group(1))
    return {"name": nome, "url": meta("og:url") or url, "image": imagem, "price": preco,
            "category": "", "description": meta("og:description")}


def singular(texto):
    """"Discos Diamantados" -> "disco diamantado"; "metais" -> "metal" (busca por produto, não categoria)."""
    palavras = []
    for p in sem_acento(texto).split():
        if p.endswith("ais"):
            p = p[:-3] + "al"
        elif p.endswith("oes"):
            p = p[:-3] + "ao"
        elif len(p) > 3 and p.endswith("s") and not p.endswith("ss"):
            p = p[:-1]
        palavras.append(p)
    return " ".join(palavras)


def buscar_bing(consulta, limite=10):
    """URLs orgânicas do Bing Brasil; o link vem em /ck/a?u=a1<base64 do destino>."""
    import base64
    import requests
    from urllib.parse import parse_qs
    from bs4 import BeautifulSoup
    try:
        r = requests.get("https://www.bing.com/search",
                         params={"q": consulta, "setlang": "pt-br", "cc": "br"},
                         headers={"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                                 "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
                                  "Accept-Language": "pt-BR,pt;q=0.9"}, timeout=20)
    except requests.RequestException:
        return []
    urls = []
    for a in BeautifulSoup(r.text, "html.parser").select("li.b_algo h2 a"):
        href = a.get("href") or ""
        destino = parse_qs(urlparse(href).query).get("u", [""])[0]
        if destino.startswith("a1"):
            b = destino[2:] + "=" * (-len(destino[2:]) % 4)
            try:
                href = base64.urlsafe_b64decode(b).decode("utf-8", "ignore")
            except ValueError:
                continue
        href = href.split("?msockid")[0]
        if href.startswith("http") and not MARKETPLACES.search(href) and href not in urls:
            urls.append(href)
    return urls[:limite]


def variacoes_da_consulta(consulta):
    """O Bing às vezes responde a um termo com 1 ou 2 links fora do assunto ("disco
    diamantado" -> loja de vinil). Variações: sem "comprar", com "de corte"/"preço"."""
    base = re.sub(r"\s+comprar$", "", consulta).strip()
    palavras = base.split()
    saida = [consulta, f"{base} preço", f"{base} loja"]
    if len(palavras) >= 2:
        saida.append(f"{palavras[0]} de corte {' '.join(palavras[1:])}")
    return saida


def buscar_na_web(consulta, limite=10):
    """DuckDuckGo primeiro; o Bing só entra quando o DuckDuckGo traz menos de 3 links."""
    import time
    urls = buscar_duckduckgo(consulta, limite)
    if len(urls) >= 3:
        return urls
    melhor = urls
    for variacao in variacoes_da_consulta(consulta):
        urls = buscar_bing(variacao, limite)
        if len(urls) > len(melhor):
            melhor = urls
        if len(urls) >= 3:
            return urls
        time.sleep(0.5)
    return melhor


PALAVRAS_VAZIAS = {"preco", "comprar", "produto", "produtos", "linha", "nossa", "conheca", "tambem",
                   "para", "com", "sem", "de", "da", "do", "das", "dos", "e", "em", "a", "o"}


def palavras_chave(texto):
    return [p for p in re.findall(r"[a-z0-9]+", singular(texto)) if len(p) >= 3 and p not in PALAVRAS_VAZIAS]


def assunto_dos_nomes(nomes):
    """A palavra que mais se repete nos nomes do site ("bicicleta"), com acento."""
    contagem = {}
    for nome in nomes or ():
        for palavra in set(re.findall(r"[a-zà-ú]{5,}", str(nome).lower())):
            contagem[palavra] = contagem.get(palavra, 0) + 1
    if not contagem:
        return ""
    palavra, vezes = max(contagem.items(), key=lambda kv: kv[1])
    return palavra if vezes >= 3 else ""


def termos_de_busca(cliente, segmento, categorias, nomes=(), foco=""):
    """Termos específicos: nomes de produto já conhecidos (lidos no site ou na foto)
    e linhas do site com duas palavras ou mais ("disco diamantado"). Palavra solta
    ("metal") traz enciclopédia, então fica de fora."""
    termos = []
    foco_limpo = re.split(r"(?i)[,;]|\bn[aã]o\b|\bsem\b", foco or "")[0]
    assunto = assunto_dos_nomes(nomes) or (re.findall(r"[a-zà-ú]{4,}", (segmento or "").lower()) or [""])[0]
    for parte in re.split(r"\s+e\s+|/", foco_limpo):
        chave = " ".join(re.findall(r"[a-zà-ú0-9]{3,}", parte.lower())[:3])
        if chave:
            termos.append(f"{chave} para {assunto}".strip() if assunto else chave)
            termos.append(f"{chave} {assunto} {cliente}".strip())
    for n in ([] if foco_limpo.strip() else list(nomes)[:3]):
        chave = " ".join(palavras_chave(n)[:5])
        if len(chave.split()) >= 2:
            termos.append(f"{chave} comprar")
    for c in categorias:
        c = re.sub(r"(?i)^(linha de|conheça também nossa linha de|nossa linha de)\s+", "", c or "").strip()
        chave = " ".join(palavras_chave(c)[:4])
        if len(chave.split()) >= 2 and not SECAO_INSTITUCIONAL.search(c):
            termos.append(f"{chave} comprar")
    if segmento and len(palavras_chave(segmento)) >= 2:
        termos.append(f"{' '.join(palavras_chave(segmento)[:4])} comprar")
    termos.append(f"{cliente} produtos")
    vistos, saida = set(), []
    for t in termos:
        if sem_acento(t) not in vistos:
            vistos.add(sem_acento(t))
            saida.append(t)
    return saida[:5]


def relevante(nome, termo, cliente, url=""):
    """A página achada só vale se o nome do produto repete palavras do termo buscado;
    no termo com o nome do cliente, o nome ou o endereço tem que citar o cliente."""
    if sem_acento(cliente) in sem_acento(termo):
        marca = [p for p in palavras_chave(cliente) if len(p) >= 4]
        alvo = sem_acento(nome) + " " + sem_acento(url)
        return bool(marca) and any(p in alvo for p in marca)
    chaves = set(palavras_chave(termo))
    comuns = chaves & set(palavras_chave(nome))
    return len(comuns) >= min(2, len(chaves - {"corte", "loja"}))


def _ler_pagina_busca(url):
    registro = ler_mercado_livre(url) if MERCADO_LIVRE.search(url) else _ler_pagina(url)
    if not registro or CAPTCHA.search(registro.get("name") or "") or CAPTCHA.search(registro.get("description") or ""):
        return None
    return registro


def buscar_candidatos_web(cliente, segmento, categorias, site, nomes=(), limite=24, foco=""):
    """Busca na web por termos do próprio site. Página de outra marca vira candidato
    [busca]; o modelo marca do_cliente e o pedido fica com produtos_similares."""
    host = urlparse(normalizar_site(site)).hostname or ""
    pares, vistos = [], set()
    termos = termos_de_busca(cliente, segmento, categorias, nomes, foco)
    evento("extracao", "termos de busca: " + " · ".join(termos))
    for termo in termos:
        for url in buscar_na_web(termo):
            if url not in vistos and host not in url:
                vistos.add(url)
                pares.append((url, termo))
    pares = pares[:limite]
    with ThreadPoolExecutor(8) as pool:
        registros = list(pool.map(_ler_pagina_busca, [u for u, _ in pares]))
    achados, fora = [], 0
    for (url, termo), r in zip(pares, registros):
        if not r:
            continue
        if not relevante(r["name"], termo, cliente, r.get("url") or url):
            fora += 1
            continue
        achados.append(candidato(r["name"], r["url"], r["image"], r.get("price"), r.get("category"),
                                 r.get("description"), "busca"))
    evento("extracao", f"busca na web: {len(achados)} produtos em {len(pares)} páginas "
                       f"({fora} páginas fora do assunto descartadas)")
    return achados


def coletar_titulos_de_linha(base):
    """Títulos de seção que nomeiam linhas de produto ("Linha de Discos Diamantados")."""
    import requests
    from bs4 import BeautifulSoup
    try:
        pagina = requests.get(base, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    except requests.RequestException:
        return []
    titulos = []
    for h in BeautifulSoup(pagina, "html.parser").find_all(["h2", "h3"]):
        t = limpar_texto(h.get_text(" ", strip=True))
        if re.search(r"(?i)\blinha\b", t) and len(t) < 70 and not SECAO_INSTITUCIONAL.search(t):
            titulos.append(t)
    return titulos[:4]

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


class SemCreditoOpenRouter(RuntimeError):
    """HTTP 402 do OpenRouter: a conta esta sem credito para a selecao."""


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


def coletar_candidatos(site):
    coleta = _coletar(normalizar_site(site), MAXIMO_CANDIDATOS)
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
e as imagens dos primeiros candidatos. Todos já passaram por um filtro de URL e imagem.

Cliente: {cliente}
Site: {site}
Segmento informado: {segmento}

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
- Diga o segmento do cliente em poucas palavras.

Responda SOMENTE JSON:
{{"segmento": "...", "categorias": ["A", "B", "C"],
  "selecionados": [{{"n": 3, "categoria": 0, "do_cliente": true}}],
  "descartados": [{{"n": 7, "tipo": "nao_e_produto", "motivo": "slide do carrossel"}}]}}

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
        if "OPENROUTER_API_KEY" in str(erro):
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
    itens, usados, do_cliente = [], set(), {}
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
    itens = itens[:MAXIMO_PRODUTOS]
    motivos = ler_descartes(escolha, candidatos, usados)
    completados = completar_ate_o_alvo(itens, candidatos, motivos, categorias)
    for n in completados:
        do_cliente[n] = candidatos[n]["origem"] == "site"
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
        entrada = {"sku": req["payload"]["sku"], "nome": req["payload"]["name"],
                   "origem_url": c["url"], "imagem": c["imagem"], "fonte": c["origem"],
                   "do_cliente": do_cliente[n], "completado": n in completados}
        if not req.get("_preco_estimado"):
            entrada.update(origem="publico", regra="lido na página do produto")
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

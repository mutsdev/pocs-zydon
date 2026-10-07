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
MAXIMO_PRODUTOS = 15
MAXIMO_CANDIDATOS = 60
MAXIMO_IMAGENS_NO_PROMPT = 40
MAXIMO_TOKENS_SAIDA = 4000

NAO_E_PRODUTO = re.compile(
    r"\b(arrow|seta|previous|next|anterior|proximo|slide|slider|banner|carrossel|"
    r"carousel|logo|logotipo|icone|icon|favicon|whatsapp|instagram|facebook|"
    r"youtube|mapa|map|avatar|placeholder|background|fundo|hero)\b", re.I)
NOME_NAO_PRODUTO = re.compile(
    r"(?i)\b\d{2,4}x\d{2,4}\b(?!\s*(?:cm|mm|m|pol)\b)|\bico\d*\b|\be\d{8,}\b|photoroom|\bselos?\b|\bhome\s*\d+\b|"
    r"\b(img|image|imagem|foto|dsc|wp|screenshot|captura|whatsapp image)[\s_-]*\d|"
    r"\bmais de \d|\banos no mercado\b|\bclientes em todo\b|\bsmiling\b|\bheadset\b")
IMAGEM_NAO_E_PRODUTO = re.compile(
    r"(/slider/|/slides?/|/banners?/|/icons?/|/receitas?/|logo|favicon|sprite|placeholder|\.svg($|\?))", re.I)


PRAZO = {"fim": None}
QUANTOS = {"n": None}
NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
           "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12}
PEDIDO_DE_QUANTIDADE = re.compile(
    r"(?i)\b(?:apenas|somente|so|no maximo|ate|quero|traga|preciso de)?\s*"
    r"(\d{1,2}|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze)\s+"
    r"(?:produtos?|itens?|exemplos?|skus?)\b")


def quantidade_pedida(observacao):
    """(quantos, observacao_sem_a_quantidade): "Quero apenas 3 produtos" -> (3, "")."""
    texto = sem_acento(observacao or "")
    achado = PEDIDO_DE_QUANTIDADE.search(texto)
    if not achado:
        return None, observacao or ""
    valor = achado.group(1).lower()
    quantos = int(valor) if valor.isdigit() else NUMEROS.get(valor)
    if not quantos:
        return None, observacao or ""
    resto = (texto[:achado.start()] + " " + texto[achado.end():]).strip(" ,.;")
    return max(1, min(MAXIMO_PRODUTOS, quantos)), resto


def alvo_pedido():
    return QUANTOS["n"] or MAXIMO_PRODUTOS


def minimo_pedido():
    return min(MINIMO_PRODUTOS, alvo_pedido())
TEMPO_IA = {"segundos": 90, "tentativas": 2, "compativel": 150}
TETO_CONFERENCIA = 60
CUSTO_EXTRA = {"custo_usd": 0.0}
MODELOS_USADOS = []
_TRAVA_CUSTO = __import__("threading").Lock()


def registrar_modelo(modelo, custo_usd=0.0):
    """Soma custo pago fora da fila (ex.: busca do gateway) e guarda cada modelo usado no pedido."""
    with _TRAVA_CUSTO:
        if modelo and modelo not in MODELOS_USADOS:
            MODELOS_USADOS.append(modelo)
        CUSTO_EXTRA["custo_usd"] += float(custo_usd or 0)


def iniciar_prazo(segundos):
    """Relógio da extração: cada etapa extra de busca confere quanto tempo sobra."""
    import time
    PRAZO["fim"] = time.monotonic() + segundos


def restante():
    import time
    return 9999 if PRAZO["fim"] is None else PRAZO["fim"] - time.monotonic()


def em_paralelo(funcao, itens, trabalhadores=16, teto=30):
    """pool.map que não espera página lenta: o que não voltar até o teto (ou até o prazo) vira None."""
    from concurrent.futures import wait
    itens = list(itens)
    if not itens:
        return []
    pool = ThreadPoolExecutor(trabalhadores)
    futuros = [pool.submit(funcao, i) for i in itens]
    wait(futuros, timeout=max(5, min(teto, restante() - 10)))
    pool.shutdown(wait=False, cancel_futures=True)
    saida = []
    for f in futuros:
        try:
            saida.append(f.result() if f.done() else None)
        except Exception:
            saida.append(None)
    return saida


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


PALAVRAS_NEUTRAS = {"de", "da", "do", "das", "dos", "em", "com", "e", "a", "o", "para", "pet", "-", "–", "|"}


def chave_produto(nome):
    """Mesmo produto escrito de outro jeito ("Ketchup Tradicional 400g Quero" e
    "Ketchup Quero Tradicional PET 400g") dá a mesma chave: palavras sem acento, sem
    preposição e em ordem alfabética. Sabor ou tamanho diferente muda a chave."""
    palavras = re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", sem_acento(nome).lower())
    return " ".join(sorted(p for p in palavras if p not in PALAVRAS_NEUTRAS))


def nome_de_arquivo(nome):
    """Nome que é nome de arquivo ou rótulo genérico, não produto: "Imagem",
    "DISPLAY_DACOPRO_BROWNIE_800X800", "IMG_2041"."""
    limpo = sem_acento(nome or "").strip().lower()
    if limpo in {"imagem", "image", "foto", "produto", "produtos", "img", "picture", "sem titulo", "untitled"}:
        return True
    if nome.count("_") >= 2 or re.search(r"\d{2,4}\s*[x×]\s*\d{2,4}(?![\d\s]*(cm|mm|m|pol)\b)", limpo):
        return True
    return bool(re.search(r"\.(jpe?g|png|webp|gif|avif)\b", limpo))


def nome_valido(nome, url=""):
    """Codigo sem espaco ("SUP390") so vale com pagina de produto propria;
    na home e nome de arquivo de slide ("biscoito2", "pizza-1")."""
    nome = (nome or "").strip()
    if len(nome) < 4 or not re.search(r"[A-Za-zÀ-ú]{2}", nome) or nome_de_arquivo(nome):
        return False
    pagina_propria = len([p for p in urlparse(url or "").path.split("/") if p]) >= 1
    if " " not in nome and re.search(r"\d", nome) and not pagina_propria:
        return False
    if re.search(r"voce buscou|resultados? (da busca|para)|busca por", sem_acento(nome).lower()):
        return False
    if NOME_NAO_PRODUTO.search(sem_acento(nome)):
        return False
    return not NAO_E_PRODUTO.search(sem_acento(nome))


def normalizar_site(site):
    base = site.strip() if site.strip().startswith(("http://", "https://")) else "https://" + site.strip()
    base = re.split(r"[?#]", base, maxsplit=1)[0]
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
    sondas = (_shopify_com_foto, _woocommerce_com_opcoes, coletar_site.vtex,
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
            itens = [i for i in itens if i.get("imagem")] + [i for i in itens if not i.get("imagem")]
            break
    gerador = ""
    if home is not None:
        m = _re.search(r'<meta name="generator" content="([^"]+)"', home.text)
        gerador = m.group(1) if m else ""
    return {"site": base, "gerador": gerador, "plataforma": plataforma,
            "total": len(itens), "itens": itens[:limite]}


def _shopify_com_foto(base):
    """Loja Shopify: lê até 4 páginas de /products.json (250 por página) e guarda
    os produtos com foto primeiro. Antes o corte nos 60 primeiros pegava só itens
    sem foto (Ricambi: 250 produtos, 28 com foto, nenhum entre os 60 primeiros)."""
    import coletar_site
    from urllib.parse import urljoin as _junta
    saida, vistos = [], set()
    for pagina in range(1, 5):
        dados = coletar_site._json(_junta(base, f"/products.json?limit=250&page={pagina}"))
        produtos = (dados or {}).get("products") or []
        if not produtos:
            break
        for p in produtos:
            v = (p.get("variants") or [{}])[0]
            img = (p.get("images") or [{}])[0].get("src")
            chave = (p.get("title"), img)
            if chave in vistos:
                continue
            vistos.add(chave)
            try:
                preco = float(v.get("price") or 0) or None
            except (TypeError, ValueError):
                preco = None
            item = coletar_site._item(p["title"], preco, p.get("product_type"), img,
                                      _junta(base, f"/products/{p['handle']}"))
            item["opcoes"] = [{"nome": o.get("name"), "valores": o.get("values") or []}
                              for o in p.get("options") or []]
            saida.append(item)
        if len(produtos) < 250 or sum(1 for i in saida if i.get("imagem")) >= 60:
            break
    if not saida:
        return None
    com_foto = sum(1 for i in saida if i.get("imagem"))
    evento("extracao", f"loja Shopify: {len(saida)} produtos, {com_foto} com foto")
    return "shopify", saida


def _woocommerce_com_opcoes(base):
    """WooCommerce Store API do repo, guardando os termos dos atributos com variação
    (Cor: Branco, Preto) para a grade de variações."""
    import coletar_site
    from urllib.parse import urljoin as _junta
    dados = coletar_site._json(_junta(base, "/wp-json/wc/store/v1/products?per_page=100"))
    if not isinstance(dados, list) or not dados:
        return None
    saida = []
    for p in dados:
        pr = p.get("prices") or {}
        div = 10 ** int(pr.get("currency_minor_unit", 2))
        preco = float(pr.get("price") or 0) / div or None
        cat = (p.get("categories") or [{}])[0].get("name")
        img = (p.get("images") or [{}])[0].get("src")
        item = coletar_site._item(p["name"], preco, cat, img, p.get("permalink"))
        item["opcoes"] = [{"nome": a.get("name"), "valores": [t.get("name") for t in a.get("terms") or []]}
                          for a in p.get("attributes") or [] if a.get("has_variations")]
        saida.append(item)
    return "woocommerce", saida


EIXOS_CONHECIDOS = (
    ("Cor", r"^(cor|cores|color|colour)$"),
    ("Tamanho", r"^(tamanho|tam|size|numera[cç][aã]o)$"),
    ("Voltagem", r"^(voltagem|tens[aã]o|volt|voltage)$"),
    ("Volume", r"^(volume|capacidade)$"),
    ("Peso", r"^(peso|gramatura|weight)$"),
    ("Sabor", r"^(sabor|flavor|aroma)$"),
    ("Medida", r"^(medida|medidas|dimens[aã]o|di[aâ]metro|bitola|comprimento)$"),
    ("Modelo", r"^(modelo|vers[aã]o|tipo)$"),
)
MAXIMO_PRODUTOS_COM_GRADE = 12
MAXIMO_VALORES_POR_EIXO = 8


def _paleta_de_cores():
    """{nome sem acento: nome do template} da paleta de cores do repositório."""
    caminho = Path(os.environ.get("ZYDON_REPO", "")) / "Criar Portais" / "template_variacoes.json"
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        valores = dados["etapa_variations"]["requests"][0]["payload"]["values"]
    except (OSError, ValueError, KeyError, IndexError):
        return {}
    return {sem_acento(v): v for v in valores}


def grade_do_candidato(c, paleta=None):
    """(eixo, valores, observacao) ou None. Só o que o site/anexo informou: nunca inventa valor.
    Um eixo por produto (o montar_poc do repositório monta um). Cor só com nomes da paleta
    do template; o que ficar de fora vai na observação."""
    for opcao in c.get("opcoes") or []:
        nome = limpar_texto(opcao.get("nome"))
        eixo = next((rotulo for rotulo, padrao in EIXOS_CONHECIDOS
                     if re.match(padrao, sem_acento(nome))), None)
        if not eixo and nome and nome.lower() not in ("title", "opção", "opcao", "default"):
            eixo = nome[:30].capitalize()
        if not eixo:
            continue
        valores = []
        for v in opcao.get("valores") or []:
            v = limpar_texto(v)[:40]
            if v and v.lower() not in ("default title", "único", "unico", "padrão", "padrao") and v not in valores:
                valores.append(v)
        observacao = ""
        if eixo == "Cor":
            paleta = paleta if paleta is not None else _paleta_de_cores()
            aceitos = [paleta[sem_acento(v)] for v in valores if sem_acento(v) in paleta]
            fora = [v for v in valores if sem_acento(v) not in paleta]
            if fora:
                observacao = f"cores fora da paleta do template ficaram de fora: {', '.join(fora[:6])}"
            valores = list(dict.fromkeys(aceitos))
        valores = valores[:MAXIMO_VALORES_POR_EIXO]
        if len(valores) >= 2:
            return eixo, valores, observacao
    return None


PADROES_EIXO_NA_OBSERVACAO = (
    ("Tamanho", r"tamanh|numera[cç]|\bp\s*,\s*m\b"),
    ("Cor", r"\bcor(es)?\b"),
    ("Voltagem", r"voltag|\b(110|127|220)\s*v\b|bivolt"),
    ("Sabor", r"sabor"),
    ("Volume", r"volume|\bml\b|litro"),
    ("Peso", r"\bpeso\b|gramatura|\bkg\b"),
)
PARTE_DE_VARIACAO = re.compile(r"(?i)varia[cç]|\bgrade\b|tamanh|\bcor(es)?\b|voltag|sabor")


def separar_observacao(observacao):
    """(foco, eixo_pedido): as frases que falam de variação saem do foco da busca e dizem o eixo."""
    partes = [p.strip() for p in re.split(r"[.;\n]+", observacao or "") if p.strip()]
    foco = ", ".join(p for p in partes if not PARTE_DE_VARIACAO.search(p))
    texto = sem_acento(" ".join(p for p in partes if PARTE_DE_VARIACAO.search(p)))
    eixo = next((rotulo for rotulo, padrao in PADROES_EIXO_NA_OBSERVACAO if re.search(padrao, texto)), None)
    return foco, eixo


def _semente(texto):
    import hashlib
    return int(hashlib.md5(sem_acento(texto).encode()).hexdigest()[:8], 16)


CORES_SUGERIDAS = ("Preto", "Branco", "Cinza", "Azul Marinho", "Vermelho", "Verde", "Bege", "Grafite", "Azul Royal", "Rosa")


def grade_sugerida(c, segmento, eixo_pedido=None, paleta=None):
    """Quando o usuário pediu variação e o site/anexo não informa: grade fixa pela regra
    (eixo pedido na observação, senão pelo tipo de produto). Nunca vem do modelo."""
    texto = sem_acento(f"{c.get('nome')} {c.get('categoria')} {segmento}")
    eixo = eixo_pedido
    if not eixo:
        if re.search(r"cal[cç]ad|sapat|tenis|bota|sandal|chinel", texto):
            eixo = "Tamanho"
        elif re.search(r"roupa|camis|vestid|blus|calca|moda|jaquet|bermud|uniform|lingerie|meia|jeans|short|saia|macac|moleton|polo", texto):
            eixo = "Tamanho"
        elif re.search(r"eletr|motor|furadeir|lixadeir|esmerilh|ventilad|liquidific|\bvolts?\b", texto):
            eixo = "Voltagem"
        else:
            eixo = "Cor"
    if eixo == "Tamanho":
        valores = (["36", "37", "38", "39", "40", "41", "42"]
                   if re.search(r"cal[cç]ad|sapat|tenis|bota|sandal|chinel", texto) else ["P", "M", "G", "GG"])
    elif eixo == "Voltagem":
        valores = ["127V", "220V"]
    elif eixo == "Sabor":
        valores = ["Original", "Chocolate", "Morango"]
    elif eixo == "Volume":
        valores = ["500 ml", "1 L", "2 L"]
    elif eixo == "Peso":
        valores = ["500 g", "1 kg", "5 kg"]
    else:
        eixo = "Cor"
        paleta = paleta if paleta is not None else _paleta_de_cores()
        cores = [v for v in CORES_SUGERIDAS if not paleta or sem_acento(v) in paleta]
        inicio = _semente(c.get("nome") or "") % len(cores)
        valores = [cores[(inicio + k) % len(cores)] for k in range(3)]
    return eixo, valores, "variação sugerida pelo sistema: o site não informa a grade deste produto"


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
        if (urlparse(url).hostname == host and 1 <= len(partes) <= 2 and url not in links
                and not any(PAGINA_NAO_E_SECAO.search(p) for p in partes)):
            links.append(url)
    links.sort(key=lambda u: (0 if re.search(r"(?i)produto|unidade|neg[oó]cio|linha|categoria|marca|segmento|departamento",
                                             u) else 1, len([p for p in urlparse(u).path.split("/") if p])))
    itens = []
    for url in links[:14]:
        if restante() < 30:
            break
        try:
            pagina = requests.get(url, headers=cabecalho, timeout=15).text
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
    candidatos = []
    for i in coleta.get("itens") or []:
        c = candidato(i.get("nome"), i.get("url"), i.get("imagem"), i.get("preco"),
                      i.get("categoria"), i.get("descricao"), "site")
        opcoes = i.get("opcoes") or []
        if not opcoes and i.get("variantes") and coleta.get("plataforma") == "shopify":
            opcoes = [{"nome": "Opção", "valores": i["variantes"]}]
        if opcoes:
            c["opcoes"] = opcoes
        candidatos.append(c)
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


def valor_preco(bruto):
    """Preço como número. Número do JSON-LD (21.98) vale como está; texto com um só
    separador e 1-2 casas ("21.98", "21,98") é decimal; "1.234,56" tem milhar."""
    if isinstance(bruto, bool) or bruto is None:
        return None
    if isinstance(bruto, (int, float)):
        return round(float(bruto), 2) if bruto > 0 else None
    texto = re.sub(r"[^0-9.,]", "", str(bruto))
    if not texto:
        return None
    if re.fullmatch(r"\d+[.,]\d{1,2}", texto):
        texto = texto.replace(",", ".")
    elif "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(".", "")
    try:
        valor = float(texto)
    except ValueError:
        return None
    return round(valor, 2) if valor > 0 else None


def _corrigir_preco_do_repo():
    """extracao._price do repo tira o ponto de "21.98" e grava 2198 (Sam's Club,
    29/09/2026). Troca só a leitura do número; o resto do _price continua o do repo."""
    import extracao
    if getattr(extracao, "_preco_corrigido", False):
        return
    original = extracao._price

    def _price(product, soup):
        if isinstance(product, dict):
            offers = product.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            bruto = offers.get("price") if isinstance(offers, dict) else None
            if bruto is None and isinstance(offers, dict):
                bruto = offers.get("lowPrice")
            if bruto is None:
                bruto = product.get("price")
            valor = valor_preco(bruto)
            if valor:
                return valor
        for attrs in ({"property": "product:price:amount"}, {"itemprop": "price"}):
            node = soup.find("meta", attrs=attrs)
            valor = valor_preco(node.get("content") if node else None)
            if valor:
                return valor
        return original(None, soup)

    extracao._price = _price
    candidatas_originais = extracao._image_candidates

    def _image_candidates(soup, base_url, product=None):
        """Mesma lista do repo, sem SVG/logo/banner na frente e com a miniatura
        (-150-150, width=150) depois da versão grande: o repo usa a primeira."""
        todas = candidatas_originais(soup, base_url, product)
        boas = [u for u in todas if not IMAGEM_NAO_E_PRODUTO.search(u)]
        pequena = re.compile(r"(-\d{2,3}-\d{2,3}[?/]|[?&]width=\d{2,3}(&|$)|/w_\d{2,3},)")
        da_loja = re.compile(r"(file-manager|/assets/|/static/|/themes?/)", re.I)
        ordem = lambda u: (bool(da_loja.search(u)), bool(pequena.search(u)))
        return sorted(boas, key=ordem)

    extracao._image_candidates = _image_candidates
    extracao._preco_corrigido = True


def _ler_pagina(url):
    import extracao
    _corrigir_preco_do_repo()
    try:
        return extracao._record_from_page(url)
    except Exception:
        return None


URL_NAO_E_PRODUTO = re.compile(r"(/busca\b|/search\b|[?&](fq|q|s|busca|ft)=|/buscapagina)", re.I)
ARQUIVO_BANNER = re.compile(r"(banner|topo|header|cabecalho|vitrine|campanha|promo)", re.I)


def unquote_nome(url):
    from urllib.parse import unquote
    return unquote(url.split("?")[0].rsplit("/", 1)[-1])


def nome_legivel(nome):
    """'mouse-sem-fio-logitech-7-botoes-01' -> 'Mouse sem fio logitech 7 botoes'."""
    nome = (nome or "").strip()
    if " " in nome or nome.count("-") < 2:
        return nome
    partes = [p for p in re.split(r"-+", nome) if p]
    while len(partes) > 2 and re.fullmatch(r"0?\d{1,2}", partes[-1]):
        partes.pop()
    texto = " ".join(partes)
    return texto[:1].upper() + texto[1:]


def filtrar_candidatos(candidatos):
    """(validos, descartes). Toda imagem restante passa pelo verificar_imagens.py."""
    import verificar_imagens
    descartes, vistos, antes = [], set(), []
    for c in candidatos:
        motivo = None
        if c.get("nome"):
            c = dict(c, nome=nome_legivel(c["nome"]))
        arquivo_img = unquote_nome(str(c.get("imagem") or ""))
        if str(c.get("url") or "").startswith("http") and URL_NAO_E_PRODUTO.search(str(c.get("url"))):
            motivo = "link é página de busca, não de um produto"
        elif ARQUIVO_BANNER.search(arquivo_img):
            motivo = "imagem é banner da página (nome do arquivo)"
        if motivo:
            pass
        elif not str(c.get("url") or "").startswith(("http://", "https://", "anexo:")):
            motivo = "sem URL de origem"
        elif not str(c.get("imagem") or "").startswith(("http://", "https://")):
            motivo = "sem imagem da fonte"
        elif not nome_valido(c.get("nome"), c["url"]):
            motivo = "nome não parece produto"
        elif IMAGEM_NAO_E_PRODUTO.search(c["imagem"]):
            motivo = "imagem de banner, ícone ou carrossel"
        elif c["imagem"] in vistos or (c.get("origem") != "busca" and chave_produto(c["nome"]) in vistos):
            motivo = "duplicado"
        if motivo:
            descartes.append({"nome": c.get("nome"), "motivo": motivo})
            continue
        vistos.add(c["imagem"])
        if c.get("origem") != "busca":
            vistos.add(chave_produto(c["nome"]))
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
Observação do usuário (tipo de produto que ele quer no portal, público, restrições): {foco}

Regras obrigatórias:
- Escolha SOMENTE pelos números da lista. Nunca invente produto, nome, imagem ou preço.
- Quantidade: escolha TODOS os produtos reais e vendáveis, até {alvo} (há {total} candidatos).
  Mais produtos é melhor: nunca deixe de fora um produto real só para variar ou enxugar.
  Só escolha menos se não houver {alvo} produtos reais; nesse caso explique cada descarte.
- Descarte o que não é produto vendável: banner, slide de carrossel, seta de navegação,
  ícone, logo, foto institucional, foto de ambiente, depoimento de cliente, nome de
  categoria ou menu ("CERAS", "PNEUS"), contato, blog.
  Exemplos que NÃO são produto: "biscoito2" (slide do carrossel), "previous arrow",
  "logiscal home ico1 150x120" (ícone), "mais de 20 mil clientes" (número institucional),
  "selo reforma" (selo), foto de pessoa/atendente, nome que é nome de arquivo de imagem.
- Se sobrarem menos de {alvo} produtos reais, escolha MENOS: nunca complete com o que não é produto.
- Olhe a imagem: banner com texto promocional, arte de carrossel, ícone ou foto de
  ambiente é descarte, mesmo que o nome pareça produto.
- Priorize produtos da marca/catálogo do próprio cliente. Candidato [busca] que não é do
  cliente só entra se faltar produto do site; marque "do_cliente": false. Quando há poucos
  ou nenhum candidato [site], ESCOLHA os [busca] do mesmo tipo que o cliente vende (são
  exemplos similares, o portal avisa): não descarte por "outra_marca" nesse caso.
- Produto do site cujo NOME traz a marca de outra empresa (licenciamento ou revenda,
  ex.: "Moedor de Sal com Chimichurri Brahma" no site da Kisabor) é "outra_marca": só entra
  se faltar produto com a marca do cliente. Linhas e submarcas do próprio cliente valem.
- Espalhe a escolha entre as categorias do site (campo "categoria" dos candidatos): pegue
  de todas antes de repetir a mesma. Sabores e versões diferentes são produtos diferentes e entram;
  só descarte como "repetido" o mesmo produto em outro tamanho quando ainda faltar produto para o alvo.
- Agrupe os escolhidos em exatamente 3 categorias com nomes curtos em português; use os
  nomes das categorias do site quando existirem.
- Para CADA candidato não escolhido, devolva o número e o motivo em uma frase curta, com
  o tipo: "nao_e_produto", "outra_marca", "repetido" (variação/tamanho de um escolhido)
  ou "limite" (produto bom que ficou de fora pela quantidade ou pela variedade).
- Se há observação do usuário (ex.: "só produtos femininos"), escolha PRIMEIRO os candidatos que a atendem e
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
        r = requests.get(url, timeout=20, stream=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                   "AppleWebKit/537.36 Chrome/128.0 Safari/537.36"})
        if r.status_code != 200:
            return None
        bruto = bytearray()
        for bloco in r.iter_content(65536):
            bruto.extend(bloco)
            if len(bruto) > 15_000_000:
                r.close()
                return None
        Image.MAX_IMAGE_PIXELS = 40_000_000
        with Image.open(io.BytesIO(bytes(bruto))) as original:
            original.draft("RGB", (512, 512))
            imagem = original.convert("RGB")
        imagem.thumbnail((512, 512))
        saida = io.BytesIO()
        imagem.save(saida, "JPEG", quality=80)
        return "image/jpeg", base64.b64encode(saida.getvalue()).decode()
    except Exception:
        return None


CLOUDFLARE_MODELOS = ("@cf/meta/llama-4-scout-17b-16e-instruct", "@cf/mistralai/mistral-small-3.1-24b-instruct")
NVIDIA_MODELOS = ("meta/llama-4-maverick-17b-128e-instruct", "meta/llama-3.2-90b-vision-instruct")
IAS_SEM_COTA = set()


class SemCotaNestaIA(RuntimeError):
    """Esta IA da fila respondeu sem cota ou fora do ar; passa para a próxima."""


def _texto_json(texto):
    texto = re.sub(r"^```(?:json)?|```$", "", (texto or "").strip()).strip()
    if not texto.startswith("{"):
        achado = re.search(r"\{.*\}", texto, re.S)
        texto = achado.group(0) if achado else texto
    return json.loads(texto)


def _imagens_baixadas(mensagens):
    urls = [c["image_url"]["url"] for m in mensagens if not isinstance(m["content"], str)
            for c in m["content"] if c.get("type") == "image_url"]
    with ThreadPoolExecutor(3) as pool:
        return dict(zip(urls, pool.map(_imagem_inline, urls)))


def _mensagens_inline(mensagens, baixadas):
    """Formato OpenAI com as imagens em data URI (Cloudflare e NVIDIA não baixam URL de terceiros)."""
    saida = []
    for m in mensagens:
        if isinstance(m["content"], str):
            saida.append(m)
            continue
        partes = []
        for c in m["content"]:
            if c.get("type") == "text":
                partes.append(c)
            elif baixadas.get(c["image_url"]["url"]):
                mime, dados = baixadas[c["image_url"]["url"]]
                partes.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{dados}"}})
            else:
                partes.append({"type": "text", "text": "(imagem não pôde ser baixada)"})
        saida.append({"role": m["role"], "content": partes})
    return saida


def _ia_gemini(mensagens, baixadas):
    import requests
    import time
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise SemCotaNestaIA("GEMINI_API_KEY não cadastrada")
    partes = []
    for mensagem in mensagens:
        conteudo = mensagem["content"]
        if isinstance(conteudo, str):
            partes.append({"text": conteudo})
            continue
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
    ultimo = ""
    for modelo in (MODELO_SELECAO,) + MODELOS_RESERVA:
        if ("gemini", modelo) in IAS_SEM_COTA:
            continue
        for tentativa in range(TEMPO_IA["tentativas"]):
            try:
                resposta = requests.post(GEMINI_URL.format(modelo=modelo), json=corpo_pedido,
                                         headers={"x-goog-api-key": chave}, timeout=TEMPO_IA["segundos"])
            except requests.RequestException as erro:
                ultimo = type(erro).__name__
                continue
            if resposta.status_code == 200:
                corpo = resposta.json()
                cand = (corpo.get("candidates") or [{}])[0]
                texto = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or []
                                if not p.get("thought"))
                uso = corpo.get("usageMetadata") or {}
                return _texto_json(texto), {"modelo": modelo, "custo_usd": 0.0,
                                            "tokens_entrada": uso.get("promptTokenCount") or 0,
                                            "tokens_saida": (uso.get("candidatesTokenCount") or 0)
                                            + (uso.get("thoughtsTokenCount") or 0)}
            ultimo = f"HTTP {resposta.status_code}"
            if resposta.status_code == 429:
                IAS_SEM_COTA.add(("gemini", modelo))
                break
            if resposta.status_code not in (500, 503):
                break
            time.sleep(4)
    raise SemCotaNestaIA(f"Gemini indisponível ({ultimo})")


def _ia_openai_compativel(nome, url, chave, modelos, mensagens, baixadas, extra=None):
    import requests
    ultimo = ""
    corpo_msgs = _mensagens_inline(mensagens, baixadas)
    for modelo in modelos:
        if (nome, modelo) in IAS_SEM_COTA:
            continue
        pedido = {"model": modelo, "messages": corpo_msgs, "temperature": 0,
                  "max_tokens": MAXIMO_TOKENS_SAIDA, **(extra or {})}
        try:
            resposta = requests.post(url, json=pedido, timeout=TEMPO_IA["compativel"],
                                     headers={"Authorization": f"Bearer {chave}"})
        except requests.RequestException as erro:
            ultimo = type(erro).__name__
            continue
        if resposta.status_code != 200:
            ultimo = f"HTTP {resposta.status_code}: {resposta.text[:120]}"
            if resposta.status_code in (402, 429):
                IAS_SEM_COTA.add((nome, modelo))
            continue
        corpo = resposta.json()
        texto = corpo["choices"][0]["message"].get("content") or ""
        try:
            dados = _texto_json(texto)
        except ValueError:
            ultimo = "resposta sem JSON"
            continue
        uso = corpo.get("usage") or {}
        return dados, {"modelo": f"{nome}:{modelo}", "custo_usd": uso.get("cost") or 0.0,
                       "tokens_entrada": uso.get("prompt_tokens") or 0,
                       "tokens_saida": uso.get("completion_tokens") or 0}
    raise SemCotaNestaIA(f"{nome} indisponível ({ultimo})")


def _ia_cloudflare(mensagens, baixadas):
    conta = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not (conta and token):
        raise SemCotaNestaIA("chaves da Cloudflare não cadastradas")
    url = f"https://api.cloudflare.com/client/v4/accounts/{conta}/ai/v1/chat/completions"
    return _ia_openai_compativel("cloudflare", url, token, CLOUDFLARE_MODELOS, mensagens, baixadas)


def _ia_nvidia(mensagens, baixadas):
    chave = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not chave:
        raise SemCotaNestaIA("NVIDIA_API_KEY não cadastrada")
    return _ia_openai_compativel("nvidia", "https://integrate.api.nvidia.com/v1/chat/completions",
                                 chave, NVIDIA_MODELOS, mensagens, baixadas)


def _ia_openrouter(mensagens, baixadas):
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SemCotaNestaIA("OPENROUTER_API_KEY não cadastrada")
    try:
        return _chamar_openrouter_pago(mensagens)
    except SemCreditoOpenRouter as erro:
        raise SemCotaNestaIA(str(erro)[:160])
    except RuntimeError as erro:
        raise SemCotaNestaIA(str(erro)[:160])


BARROSO_VISAO = {}
_TRAVA_VISAO = __import__("threading").Lock()


def _barroso_enxerga(chave):
    """Teste uma vez por pedido: um quadrado vermelho sólido; só vale se o modelo disser vermelho.
    Evita aprovar foto 'às cegas' quando o gateway ignora a imagem sem dar erro."""
    import base64
    import io
    import requests
    from PIL import Image
    with _TRAVA_VISAO:
        if "ok" in BARROSO_VISAO:
            return BARROSO_VISAO["ok"]
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (220, 20, 20)).save(buf, format="PNG")
        url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        pedido = {"model": MODELO_BUSCA, "max_output_tokens": 50, "input": [{"role": "user", "content": [
            {"type": "input_text", "text": "Qual é a cor desta imagem? Responda só o nome da cor, uma palavra."},
            {"type": "input_image", "image_url": url}]}]}
        texto = ""
        try:
            r = requests.post(BARROSO_URL, json=pedido, headers={"Authorization": "Bearer " + chave}, timeout=30)
            if r.status_code == 200:
                corpo = r.json() or {}
                texto = corpo.get("output_text") or ""
                if not texto:
                    for item in corpo.get("output") or []:
                        for parte in item.get("content") or []:
                            texto += (parte.get("text") or "") + " "
        except (requests.RequestException, ValueError):
            pass
        ok = bool(re.search(r"(?i)vermelh|\bred\b", texto))
        BARROSO_VISAO["ok"] = ok
        evento("extracao", "barroso-chat " + ("enxerga imagem: conferência de fotos vai por ele"
                                              if ok else "não enxerga imagem: conferência de fotos segue pelo Gemini e reservas"),
               "info" if ok else "aviso")
        return ok


def _ia_barroso(mensagens, baixadas):
    """barroso-chat (gateway Barroso, formato Responses). Imagens vão em data URI; se o
    gateway recusar imagem, sai da fila para chamadas com foto e a próxima IA assume."""
    import requests
    chave = os.environ.get("BARROSO_API_KEY", "").strip()
    if not chave:
        raise SemCotaNestaIA("BARROSO_API_KEY não cadastrada")
    com_imagem = bool(baixadas)
    if ("barroso", "imagem" if com_imagem else "texto") in IAS_SEM_COTA:
        raise SemCotaNestaIA("barroso-chat fora da fila neste pedido")
    if com_imagem and not _barroso_enxerga(chave):
        IAS_SEM_COTA.add(("barroso", "imagem"))
        raise SemCotaNestaIA("barroso-chat não enxerga imagem (teste de cor falhou)")
    entrada = []
    for m in mensagens:
        if isinstance(m["content"], str):
            entrada.append({"role": m["role"], "content": [{"type": "input_text", "text": m["content"]}]})
            continue
        partes = []
        for c in m["content"]:
            if c.get("type") == "text":
                partes.append({"type": "input_text", "text": c["text"]})
            elif baixadas.get(c["image_url"]["url"]):
                mime, dados = baixadas[c["image_url"]["url"]]
                partes.append({"type": "input_image", "image_url": f"data:{mime};base64,{dados}"})
            else:
                partes.append({"type": "input_text", "text": "(imagem não pôde ser baixada)"})
        entrada.append({"role": m["role"], "content": partes})
    pedido = {"model": MODELO_BUSCA, "input": entrada, "max_output_tokens": MAXIMO_TOKENS_SAIDA}
    try:
        r = requests.post(BARROSO_URL, json=pedido, headers={"Authorization": "Bearer " + chave},
                          timeout=TEMPO_IA["compativel"])
    except requests.RequestException as erro:
        raise SemCotaNestaIA(f"barroso-chat fora do ar ({type(erro).__name__})")
    if r.status_code != 200:
        if r.status_code in (401, 402, 403, 429):
            IAS_SEM_COTA.update({("barroso", "imagem"), ("barroso", "texto")})
        elif com_imagem and r.status_code in (400, 415, 422):
            IAS_SEM_COTA.add(("barroso", "imagem"))
        raise SemCotaNestaIA(f"barroso-chat HTTP {r.status_code}")
    corpo = r.json() or {}
    texto = corpo.get("output_text") or ""
    if not texto:
        for item in corpo.get("output") or []:
            for parte in item.get("content") or []:
                texto += (parte.get("text") or "") + "\n"
    if com_imagem and re.search(r"(?i)(n[aã]o (consigo|posso) (ver|visualizar|abrir)|can.?t (see|view)|no image)", texto):
        IAS_SEM_COTA.add(("barroso", "imagem"))
        raise SemCotaNestaIA("barroso-chat não leu as imagens")
    dados = _texto_json(texto)
    uso = corpo.get("usage") or {}
    custo = corpo.get("cost")
    return dados, {"modelo": MODELO_BUSCA, "custo_usd": custo if isinstance(custo, (int, float)) else 0.0,
                   "tokens_entrada": uso.get("input_tokens") or 0,
                   "tokens_saida": uso.get("output_tokens") or 0}


FILA_DE_IAS = (("barroso-chat", _ia_barroso), ("Gemini", _ia_gemini), ("Cloudflare Workers AI", _ia_cloudflare),
               ("NVIDIA", _ia_nvidia), ("OpenRouter", _ia_openrouter))


def _chamar_openrouter(mensagens, pular=()):
    """Fila de IAs gratuitas: tenta cada uma na ordem; a que responde sem cota sai da fila
    até o fim da execução. Só falha quando todas falharem, com o motivo de cada uma."""
    baixadas = _imagens_baixadas(mensagens)
    motivos = []
    for nome, chamar in FILA_DE_IAS:
        if nome in pular:
            continue
        try:
            resultado = chamar(mensagens, baixadas)
        except SemCotaNestaIA as erro:
            motivos.append(f"{nome}: {erro}")
            continue
        except ValueError as erro:
            motivos.append(f"{nome}: resposta inválida ({erro})")
            continue
        registrar_modelo(resultado[1].get("modelo"))
        if motivos:
            evento("extracao", f"IA usada: {resultado[1]['modelo']} (antes: {' · '.join(motivos)})"[:480], "aviso")
        return resultado
    raise SemCreditoOpenRouter("nenhuma IA gratuita respondeu agora: " + " · ".join(motivos)[:600])


INSTRUCAO_CONFERIR_FOTO = """Você confere fotos de produtos de um catálogo B2B do cliente "{cliente}".
Para cada item abaixo há o NOME anunciado e a FOTO. Diga se a foto mostra de fato aquele produto
(o mesmo tipo de item do nome; embalagem do produto vale). NÃO confere quando a foto é: logo,
banner, slide de carrossel, seta, ícone, foto de loja/fachada/pessoas, texto sem produto, ou um
produto de outro tipo (ex.: nome diz "disco de corte" e a foto é uma bicicleta).
Diferença de peso, tamanho, gramatura ou texto da embalagem (ex.: "210g líquido / 130g drenado")
NÃO é motivo para recusar: confere quando é o mesmo produto. Recuse sabor ou variação claramente
diferente do nome (ex.: nome diz "tradicional" e a foto é "cereja").
Não invente: descreva só o que aparece na foto.
Responda só JSON: {{"itens": [{{"n": 0, "confere": true, "o_que_aparece": "disco de desbaste amarelo"}}]}}

Itens:
{lista}"""


def _conferir_lote(lote, cliente, pular=()):
    lista = "\n".join(f"{n}. {c['nome'][:110]}" for n, c in enumerate(lote))
    conteudo = [{"type": "text", "text": INSTRUCAO_CONFERIR_FOTO.format(cliente=cliente, lista=lista)}]
    for n, c in enumerate(lote):
        conteudo += [{"type": "text", "text": f"Foto do item {n} ({c['nome'][:80]}):"},
                     {"type": "image_url", "image_url": {"url": c["imagem"]}}]
    return _chamar_openrouter([{"role": "user", "content": conteudo}], pular=pular)


def _segunda_opiniao(lote, cliente, resposta, custo_lote):
    """Lote inteiro recusado pelo barroso-chat: outra IA da fila confere as mesmas fotos.
    Vale a segunda resposta (o barroso já recusou fotos certas de sites institucionais)."""
    laudos = [i for i in (resposta.get("itens") or []) if isinstance(i, dict)]
    if len(lote) < 2 or not laudos or any(i.get("confere") is not False for i in laudos):
        return resposta, custo_lote
    if not str(custo_lote.get("modelo") or "").startswith(MODELO_BUSCA):
        return resposta, custo_lote
    exemplos = " · ".join(limpar_texto(i.get("o_que_aparece") or "")[:60] for i in laudos[:3])
    evento("extracao", f"barroso-chat recusou as {len(lote)} fotos do lote ({exemplos}); pedindo segunda opinião", "aviso")
    try:
        outra, custo_outra = _conferir_lote(lote, cliente, pular=("barroso-chat",))
    except Exception as erro:
        evento("extracao", f"segunda opinião indisponível ({type(erro).__name__}); mantendo a recusa", "aviso")
        return resposta, custo_lote
    aprovadas = sum(1 for i in (outra.get("itens") or []) if isinstance(i, dict) and i.get("confere") is not False)
    evento("extracao", f"segunda opinião ({custo_outra.get('modelo')}): {aprovadas} de {len(lote)} fotos conferem")
    soma = dict(custo_outra)
    for k in ("custo_usd", "tokens_entrada", "tokens_saida"):
        soma[k] = (custo_lote.get(k) or 0) + (custo_outra.get(k) or 0)
    return outra, soma


def conferir_fotos(candidatos, cliente, por_chamada=CONFERENCIA_POR_CHAMADA, teto=None):
    """(aprovados, descartes, custo). O modelo olha cada foto e diz se é o produto do nome.
    Os lotes vão ao mesmo tempo e com prazo curto: lote que não volta até o teto passa sem
    conferência (a conferência nunca inventa nem apaga em silêncio)."""
    from concurrent.futures import wait
    custo = {"custo_usd": 0.0, "tokens_entrada": 0, "tokens_saida": 0}
    aprovados, descartes = [], []
    teto = TETO_CONFERENCIA if teto is None else max(10, teto)
    lotes = [candidatos[i:i + por_chamada] for i in range(0, len(candidatos), por_chamada)]
    if not lotes:
        return aprovados, descartes, custo
    antes = dict(TEMPO_IA)
    TEMPO_IA.update(segundos=40, tentativas=1, compativel=45)
    pool = ThreadPoolExecutor(len(lotes))
    futuros = [pool.submit(_conferir_lote, lote, cliente) for lote in lotes]
    wait(futuros, timeout=teto)
    pool.shutdown(wait=False, cancel_futures=True)
    TEMPO_IA.update(antes)
    sem_credito = []
    for lote, futuro in zip(lotes, futuros):
        if not futuro.done():
            evento("extracao", f"conferência de {len(lote)} fotos passou de {teto:.0f}s; "
                               "itens seguem sem conferência", "aviso")
            aprovados += [dict(c, foto_conferida=False) for c in lote]
            continue
        try:
            resposta, custo_lote = futuro.result()
            resposta, custo_lote = _segunda_opiniao(lote, cliente, resposta, custo_lote)
        except SemCreditoOpenRouter as erro:
            sem_credito.append(erro)
            aprovados += [dict(c, foto_conferida=False) for c in lote]
            continue
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
    if sem_credito and len(sem_credito) == len(lotes):
        raise sem_credito[0]
    evento("extracao", f"fotos conferidas pelo modelo: {len(aprovados)} aprovadas, "
                       f"{len(descartes)} recusadas"
           + (" · recusas: " + " · ".join(f"{d['nome'][:40]} ({d['motivo'][31:91]})" for d in descartes[:4])
              if descartes else ""))
    return aprovados, descartes, custo


def conferir_ate(candidatos, cliente, alvo=None, reserva=6):
    """Confere só os `alvo` primeiros e, ao mesmo tempo, uma reserva com os próximos.
    Foto recusada puxa o próximo da fila até completar o alvo ou acabar o tempo."""
    import time
    alvo = alvo or alvo_pedido()
    fim = time.monotonic() + TETO_CONFERENCIA + 30
    custo = {"custo_usd": 0.0, "tokens_entrada": 0, "tokens_saida": 0}
    aprovados, descartes, posicao, rodada = [], [], 0, alvo + reserva
    while posicao < len(candidatos) and len(aprovados) < alvo:
        sobra = fim - time.monotonic()
        if sobra < 15:
            break
        lote = candidatos[posicao:posicao + rodada]
        posicao += len(lote)
        novos, recusados, custo_rodada = conferir_fotos(lote, cliente, por_chamada=min(alvo, CONFERENCIA_POR_CHAMADA), teto=min(TETO_CONFERENCIA, sobra))
        aprovados += novos
        descartes += recusados
        for k in custo:
            custo[k] += custo_rodada.get(k) or 0
        rodada = max(4, alvo - len(aprovados) + 2)
    if len(aprovados) < alvo and posicao < len(candidatos):
        aprovados += [dict(c, foto_conferida=False) for c in candidatos[posicao:posicao + alvo - len(aprovados)]]
    return aprovados, descartes, custo


def selecionar(candidatos, cliente, site, segmento, foco="", licoes=None):
    linhas = []
    for n, c in enumerate(candidatos):
        arquivo = c["imagem"].split("?")[0].rsplit("/", 1)[-1][:60]
        linhas.append(f"{n}. [{c['origem']}] {c['nome'][:110]} | categoria: {c.get('categoria') or '-'}"
                      f" | url: {c['url'][:120]} | imagem: {arquivo}"
                      f" | {(c.get('descricao') or '')[:140]}")
    texto = INSTRUCAO_SELECAO.format(cliente=cliente, site=site, segmento=segmento or "não informado",
                                     foco=foco or "nenhum (catálogo variado do cliente)",
                                     alvo=min(alvo_pedido(), len(candidatos)),
                                     total=len(candidatos), lista="\n".join(linhas))
    if MARCAS["lista"]:
        bloco = (f"Marcas que o cliente trabalha (lidas no site dele): {', '.join(MARCAS['lista'])}. "
                 "Só entra produto cujo NOME cita uma dessas marcas (\"do_cliente\": true). "
                 "Produto cujo nome não cita nenhuma delas nunca entra: descarte com tipo \"outra_marca\", "
                 "mesmo que o link seja de uma vitrine da marca.")
        texto = texto.replace("\n\nCandidatos:\n", f"\n\n{bloco}\n\nCandidatos:\n", 1)
    if licoes:
        bloco = ("Lições das avaliações dos portais anteriores (feitas pelo time; siga-as, "
                 "sem quebrar as regras acima):\n" + "\n".join(f"- {l}" for l in licoes[:15]))
        texto = texto.replace("\n\nCandidatos:\n", f"\n\n{bloco}\n\nCandidatos:\n", 1)
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
    """Com mais validos que o alvo saem o alvo: completa com os 'limite' e 'sem_motivo', na ordem,
    alternando categoria do site para espalhar. Nunca com 'nao_e_produto'."""
    alvo = min(alvo_pedido(), len(candidatos))
    usados = {n for n, _ in itens}
    curto = len(candidatos) <= alvo_pedido()
    tipo = lambda n: motivos.get(n, ("",))[0]
    sobra = [n for n in range(len(candidatos)) if n not in usados
             and (tipo(n) in ("limite", "sem_motivo")
                  or (curto and tipo(n) not in ("nao_e_produto", "outra_marca", "fora_do_foco")))]
    if len(itens) + len(sobra) < alvo:
        similares = [n for n in range(len(candidatos)) if n not in usados and n not in sobra
                     and tipo(n) in ("outra_marca", "fora_do_foco")
                     and candidatos[n].get("foto_conferida") is not False]
        sobra += similares
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


def montar_pela_selecao(coleta, candidatos, escolha, cliente, segmento, descricao, com_variacoes=False, eixo_pedido=None):
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
        if MARCAS["lista"] and candidatos[n]["origem"] not in ("site", "anexo"):
            do_cliente[n] = cita_marca(candidatos[n]["nome"])
        if s.get("no_foco") is False:
            fora_do_foco.add(n)
    itens = itens[:alvo_pedido()]
    motivos = ler_descartes(escolha, candidatos, usados)
    completados = completar_ate_o_alvo(itens, candidatos, motivos, categorias)
    for n in completados:
        do_cliente[n] = candidatos[n]["origem"] in ("site", "anexo") or (
            bool(MARCAS["lista"]) and cita_marca(candidatos[n]["nome"]))
        motivos.pop(n, None)
    descartes_modelo = [{"nome": candidatos[n]["nome"], "tipo": tipo, "motivo": f"modelo: {motivo}"}
                        for n, (tipo, motivo) in sorted(motivos.items())]
    if not itens:
        raise PrecisaCatalogo(
            f"só {len(itens)} produtos reais com URL de origem e imagem válida "
            f"(mínimo {MINIMO_PRODUTOS}); mande o catálogo em PDF ou planilha",
            {"descartes_modelo": descartes_modelo})
    coleta_montagem = {"site": coleta.get("site"), "plataforma": coleta.get("plataforma"),
                       "itens": [{"nome": c["nome"], "preco": c["preco"] if _tem_preco(c) else None,
                                  "categoria": c["categoria"], "imagem": c["imagem"], "url": c["url"],
                                  "descricao": c.get("descricao") or ""} for c in candidatos]}
    paleta = _paleta_de_cores()
    grade, grade_info = {}, {}
    for n, _ in (itens if com_variacoes else []):
        if len(grade) >= MAXIMO_PRODUTOS_COM_GRADE:
            break
        achada = grade_do_candidato(candidatos[n], paleta)
        if achada and eixo_pedido and achada[0] != eixo_pedido:
            achada = None
        if not achada:
            achada = grade_sugerida(candidatos[n], segmento, eixo_pedido, paleta)
        if achada:
            eixo, valores, observacao = achada
            grade[n] = (eixo, valores)
            grade_info[n] = {"eixo": eixo, "valores": valores, "observacao": observacao}
    if grade:
        evento("extracao", f"variações: {len(grade)} produtos com grade ("
               + "; ".join(f"{candidatos[n]['nome'][:40]}: {g[0]} {', '.join(g[1])}" for n, g in grade.items())[:600]
               + ")")
    catalogo = montar_poc.montar(coleta_montagem, cliente, (segmento or "Comércio B2B")[:120],
                                 descricao or f"{cliente} — catálogo B2B", categorias, itens, grade=grade)
    requisicoes = next(e for e in catalogo["etapas"] if e.get("endpoint") == "products")["requests"]
    publicos = [candidatos[n]["preco"] for n, _ in itens if _tem_preco(candidatos[n])]
    mesmo_site = len({urlparse(candidatos[n]["url"]).netloc.replace("www.", "") for n, _ in itens}) <= 1
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
        if n in grade_info:
            entrada["variacoes"] = grade_info[n]
        if not req.get("_preco_estimado"):
            entrada.update(origem="publico", regra=("lido no anexo do cliente" if c["origem"] == "anexo"
                                                   else "lido na página do produto"))
        elif publicos and mesmo_site:
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
                       + (f" (tabela faixas_preco.json v{faixas.versao})" if not (publicos and mesmo_site) else ""))
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
        for texto in (texto_segmento, " ".join(nomes)):
            melhor, pontos = None, 0
            for s in self.dados["segmentos"]:
                p = self._pontos(texto, s["radicais"])
                if p > pontos:
                    melhor, pontos = s, p
            if melhor:
                return melhor
        return None

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


BARROSO_URL = "https://keys.barroso.tec.br/v1/responses"
MODELO_BUSCA = "barroso-chat"
BARROSO_FORA = {"sim": False}
URL_NO_TEXTO = re.compile(r"https?://[^\s<>\"')\]]+")


def buscar_barroso(consulta, limite=10):
    """URLs achadas pela busca na web do gateway Barroso (modelo barroso-chat com a
    ferramenta web_search). O modelo só devolve ENDEREÇOS; cada página é lida e conferida
    depois, como qualquer resultado de busca. Sem chave ou com erro, devolve [] e a busca
    segue pelo DuckDuckGo/Bing."""
    import requests
    chave = os.environ.get("BARROSO_API_KEY", "").strip()
    if not chave or BARROSO_FORA["sim"] or restante() < 20:
        return []
    pedido = {"model": MODELO_BUSCA, "tools": [{"type": "web_search"}],
              "input": (f"Pesquise na web: {consulta}\n"
                        f"Responda SOMENTE com até {limite} URLs de páginas reais que apareceram na busca, "
                        "uma por linha, sem comentários e sem parâmetros de rastreamento. "
                        "Prefira páginas de lojas e sites de empresas brasileiras; nada de redes sociais, "
                        "notícias, Wikipédia ou marketplaces.")}
    try:
        r = requests.post(BARROSO_URL, json=pedido, headers={"Authorization": "Bearer " + chave},
                          timeout=max(15, min(60, restante() - 10)))
    except requests.RequestException as erro:
        evento("extracao", "busca do gateway fora do ar (" + type(erro).__name__ + "); usando a busca comum", "aviso")
        return []
    if r.status_code in (401, 402, 403, 429):
        BARROSO_FORA["sim"] = True
        evento("extracao", f"busca do gateway recusada (HTTP {r.status_code}); usando a busca comum até o fim deste pedido", "aviso")
        return []
    if r.status_code != 200:
        evento("extracao", f"busca do gateway respondeu HTTP {r.status_code}; usando a busca comum", "aviso")
        return []
    try:
        corpo = r.json() or {}
    except ValueError:
        return []
    texto = corpo.get("output_text") or ""
    if not texto:
        for item in corpo.get("output") or []:
            for parte in item.get("content") or []:
                texto += (parte.get("text") or "") + "\n"
    urls = []
    for href in URL_NO_TEXTO.findall(texto):
        href = href.rstrip(".,;:")
        if not MARKETPLACES.search(href) and not MERCADO_LIVRE.search(href) and href not in urls:
            urls.append(href)
    custo = corpo.get("cost")
    registrar_modelo(MODELO_BUSCA, custo if isinstance(custo, (int, float)) else 0)
    evento("extracao", f"busca na web pelo gateway ({MODELO_BUSCA}): {len(urls)} links para \"{consulta[:80]}\""
           + (f", custo US$ {float(custo):.4f}" if isinstance(custo, (int, float)) else ""))
    return urls[:limite]


INSTRUCAO_BARROSO_TUDO = """Você monta o catálogo de demonstração de um portal B2B para o cliente "{cliente}".
Site do cliente: {site}
Observação do usuário: {observacao}

Pesquise na web por conta própria: primeiro o site do cliente (entenda o que ele VENDE, pelas páginas e textos
dele, nunca pelo nome da empresa); se o site tiver página de produto, use as do site. Se o site não tiver
produtos suficientes, procure na web produtos do MESMO tipo que o cliente vende (lojas brasileiras).
Respeite a observação (quantidade, categorias, restrições).

Regras:
- Traga {alvo} produtos REAIS e vendáveis (sobram de reserva), cada um com a URL da PÁGINA DO PRODUTO que
  você abriu (uma página por produto, com foto; nunca home, categoria, blog ou página de orçamento sem foto).
- "imagem" é OBRIGATÓRIA: a URL direta da foto do produto (jpg/png/webp) que aparece nessa página.
  Produto sem foto não serve: troque por outro que tenha.
- Nunca traga selo, ícone, banner, foto institucional, texto da home, serviço, software ou livro, a menos
  que o site diga que o cliente vende isso.
- "preco" em reais (número) só se aparecer na página; senão null.

Responda SOMENTE JSON:
{{"o_que_vende": "frase curta", "segmento": "2 a 5 palavras",
  "tipos_de_produto": ["3 a 5 tipos concretos que um comprador digitaria numa loja, ex.: arroz 5kg, detergente"],
  "produtos": [{{"nome": "...", "url": "https://...", "imagem": "https://...", "preco": null,
                 "categoria": "...", "descricao": "uma frase"}}]}}"""


def _ler_og(url):
    """Foto, nome e preço pelas meta tags (og:image) quando a página não tem dados de produto."""
    import requests
    from bs4 import BeautifulSoup
    try:
        r = requests.get(url, headers={"User-Agent": "facebookexternalhit/1.1"}, timeout=15)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    sopa = BeautifulSoup(r.text, "html.parser")

    def meta(nome):
        tag = sopa.find("meta", attrs={"property": nome}) or sopa.find("meta", attrs={"name": nome})
        return (tag.get("content") or "").strip() if tag else ""
    imagem = meta("og:image") or meta("twitter:image")
    if imagem:
        imagem = urljoin(url, imagem)
    preco = None
    achado = re.search(r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)', r.text)
    if achado:
        preco = float(achado.group(1))
    return {"name": meta("og:title"), "image": imagem, "price": preco,
            "category": "", "description": meta("og:description")}


def _ler_pagina_com_foto(url):
    pagina = _ler_pagina(url) or {}
    if not pagina.get("image"):
        og = _ler_og(url) or {}
        pagina = {**og, **{k: v for k, v in pagina.items() if v}}
    if pagina:
        pagina["url"] = pagina.get("url") or url
    return pagina or None


BARROSO_INFO = {"o_que_vende": "", "tipos": []}

TERMO_GENERICO = re.compile(
    r"(?i)^\s*(os\s+)?(melhores|principais)?\s*(produtos?|ofertas?|promo[cç](ão|oes|ões)|descontos?|novidades|"
    r"lan[cç]amentos?|destaques?|mais vendidos|cadastre-se|cadastro|login|entrar|minha conta|carrinho|"
    r"atendimento|contato|institucional|sobre( n[oó]s)?|quem somos|blog|not[ií]cias|folhetos?|encartes?|"
    r"lojas?|varejo|atacado|distribui[cç][aã]o|diversos|variados|em geral|e muito mais)"
    r"(\s+(e|de|do|da|em|para)?\s*(produtos?|ofertas?|promo[cç](ão|oes|ões)|geral|diversos|variados|"
    r"atacado|varejo|qualidade|pre[cç]os?\s+baixos?))*\s*$")


def tipos_uteis(tipos):
    """Tira termos que não descrevem produto ("melhores produtos", "ofertas")."""
    saida = []
    for t in tipos or []:
        t = limpar_texto(t)
        if t and len(t) <= 60 and not TERMO_GENERICO.match(t) and len(palavras_chave(t)) >= 1 \
                and t.lower() not in [x.lower() for x in saida]:
            saida.append(t)
    return saida[:5]


def produtos_pelo_barroso(cliente, site, observacao, alvo):
    """Modo de teste: o barroso-chat recebe só o link e a observação e pesquisa tudo sozinho.
    Devolve (candidatos, segmento). Cada página citada é lida para confirmar foto e preço."""
    import requests
    from urllib.parse import urlparse
    chave = os.environ.get("BARROSO_API_KEY", "").strip()
    if not chave:
        evento("extracao", "modo barroso-chat: chave do gateway ausente; seguindo a busca normal", "aviso")
        return [], ""
    pedido = {"model": MODELO_BUSCA, "tools": [{"type": "web_search"}],
              "input": INSTRUCAO_BARROSO_TUDO.format(cliente=cliente, site=site or "sem site",
                                                     observacao=observacao or "nenhuma", alvo=max(alvo * 2, alvo + 6))}
    evento("extracao", f"modo barroso-chat: a IA pesquisa o site e a web sozinha ({MODELO_BUSCA})")
    try:
        r = requests.post(BARROSO_URL, json=pedido, headers={"Authorization": "Bearer " + chave}, timeout=240)
    except requests.RequestException as erro:
        evento("extracao", f"modo barroso-chat falhou ({type(erro).__name__}); seguindo a busca normal", "aviso")
        return [], ""
    if r.status_code != 200:
        evento("extracao", f"modo barroso-chat respondeu HTTP {r.status_code}; seguindo a busca normal", "aviso")
        return [], ""
    try:
        corpo = r.json() or {}
    except ValueError:
        return [], ""
    texto = corpo.get("output_text") or ""
    if not texto:
        for item in corpo.get("output") or []:
            for parte in item.get("content") or []:
                texto += (parte.get("text") or "") + "\n"
    custo = corpo.get("cost")
    registrar_modelo(MODELO_BUSCA, custo if isinstance(custo, (int, float)) else 0)
    try:
        dados = _texto_json(texto)
    except ValueError:
        evento("extracao", "modo barroso-chat: resposta sem JSON; seguindo a busca normal", "aviso")
        return [], ""
    BARROSO_INFO["o_que_vende"] = limpar_texto(dados.get("o_que_vende"))[:300]
    BARROSO_INFO["tipos"] = tipos_uteis(dados.get("tipos_de_produto") or [])
    itens = [p for p in (dados.get("produtos") or []) if isinstance(p, dict)
             and str(p.get("url") or "").startswith("http") and not MARKETPLACES.search(str(p.get("url")))]
    evento("extracao", f"modo barroso-chat: \"{limpar_texto(dados.get('o_que_vende'))[:160]}\" · "
                       f"{len(itens)} produtos sugeridos"
           + (f", custo US$ {float(custo):.4f}" if isinstance(custo, (int, float)) else ""))
    paginas = em_paralelo(_ler_pagina_com_foto, [p["url"] for p in itens], trabalhadores=8, teto=40)
    dominio = urlparse(normalizar_site(site)).netloc.replace("www.", "") if site else ""
    candidatos = []
    for p, pagina in zip(itens, paginas):
        pagina = pagina or {}
        imagem = pagina.get("image") or p.get("imagem") or ""
        preco = pagina.get("price") or p.get("preco")
        try:
            preco = float(preco) if preco not in (None, "") else None
        except (TypeError, ValueError):
            preco = None
        origem = "site" if dominio and dominio in urlparse(p["url"]).netloc else "busca"
        candidatos.append(candidato(p.get("nome") or pagina.get("name"), p["url"], imagem, preco,
                                    p.get("categoria") or pagina.get("category"),
                                    p.get("descricao") or pagina.get("description"), origem))
    return candidatos, limpar_texto(dados.get("segmento"))[:80]


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
    """Gateway Barroso primeiro; sem resultado, DuckDuckGo; o Bing só entra quando ainda há menos de 3 links."""
    import time
    urls = buscar_barroso(consulta, limite)
    if len(urls) >= 3:
        return urls
    urls = buscar_duckduckgo(consulta, limite) or urls
    if len(urls) >= 3:
        return urls
    melhor = urls
    for variacao in variacoes_da_consulta(consulta):
        if restante() < 30:
            break
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


FOCO_VAZIO = re.compile(r"(?i)\b(quero|queria|gostaria|preciso|busque|buscar|traga|trazer|mostre|somente|apenas|"
                        r"só|so|os|as|o|a|um|uma|uns|umas|de|da|das|do|dos|produtos?|itens?|categorias?|"
                        r"seguintes?|linhas?|foco|em|com|para|pra|nas?|nos?|tipo|tipos)\b")


def partes_do_foco(foco):
    """"Quero os produtos das seguintes categorias (bandejas, barras e bielas)" -> ["bandejas", "barras", "bielas"]."""
    texto = re.split(r"(?i)\bn[aã]o\b|\bsem\b", foco or "")[0]
    dentro = re.findall(r"\(([^)]*)\)", texto)
    if dentro:
        texto = " , ".join(dentro)
    texto = FOCO_VAZIO.sub(" ", texto)
    partes = [" ".join(p.split()) for p in re.split(r"[,;/:]|\s+e\s+|\s+ou\s+", texto)]
    return [p for p in partes if re.search(r"[a-zà-ú0-9]{3,}", p.lower())]


def casa_com_foco(candidato, foco):
    """O candidato é de alguma das categorias pedidas no foco (radical de 5 letras)."""
    chaves = {c[:5] for p in partes_do_foco(foco) for c in palavras_chave(p)}
    if not chaves:
        return True
    texto = palavras_chave(" ".join(str(candidato.get(k) or "") for k in ("nome", "categoria", "url")))
    return any(w.startswith(c) for w in texto for c in chaves)


def termos_de_busca(cliente, segmento, categorias, nomes=(), foco=""):
    """Termos específicos: nomes de produto já conhecidos (lidos no site ou na foto)
    e linhas do site com duas palavras ou mais ("disco diamantado"). Palavra solta
    ("metal") traz enciclopédia, então fica de fora."""
    termos = []
    partes_foco = partes_do_foco(foco)
    foco_limpo = " ".join(partes_foco)
    assunto = assunto_dos_nomes(nomes) or (re.findall(r"[a-zà-ú]{4,}", (segmento or "").lower()) or [""])[0]
    if assunto and any(sem_acento(assunto)[:5] in sem_acento(p) for p in partes_foco):
        assunto = ""
    for parte in partes_foco[:4]:
        chave = " ".join(re.findall(r"[a-zà-ú0-9]{3,}", parte.lower())[:3])
        if chave:
            termos.append(f"{chave} para {assunto}".strip() if assunto else f"{chave} comprar")
            termos.append(" ".join(x for x in (chave, assunto, cliente) if x))
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
        if TERMO_GENERICO.match(re.sub(r"(?i)\s+comprar$", "", t)):
            continue
        if sem_acento(t) not in vistos:
            vistos.add(sem_acento(t))
            saida.append(t)
    return saida[:5]


MARCAS = {"lista": []}
PAGINA_DE_MARCAS = re.compile(r"(?i)marcas|representad|parceir|fornecedor|nossos-clientes|clientes")
NOME_NAO_E_MARCA = re.compile(r"(?i)^(img|image|imagem|foto|banner|fundo|icon|icone|whatsapp|instagram|facebook|"
                              r"youtube|selo|mapa|bg|hero|slide|captura|screenshot)\b")


def _compacto(texto):
    return re.sub(r"[^a-z0-9]", "", sem_acento(texto))


def cita_marca(texto, marcas=None):
    """O texto cita uma das marcas? Compara palavra a palavra, juntando pares ("tech one" = "techone")."""
    marcas = MARCAS["lista"] if marcas is None else marcas
    if not marcas:
        return True
    palavras = re.findall(r"[a-z0-9]+", sem_acento(texto))
    blocos = set(palavras) | {a + b for a, b in zip(palavras, palavras[1:])} \
        | {a + b + c for a, b, c in zip(palavras, palavras[1:], palavras[2:])}
    return any(_compacto(m) in blocos for m in marcas)


def marcas_do_site(site, cliente=""):
    """Distribuidor/representante: nomes das marcas que ele trabalha, lidos nas logos da página
    de marcas do próprio site (allmor.com.br/nossos-clientes: Tech One, Svart, Code, Thork)."""
    import requests
    from urllib.parse import unquote
    base = normalizar_site(site)
    cabecalho = {"User-Agent": "Mozilla/5.0"}
    try:
        home = requests.get(base, headers=cabecalho, timeout=15).text
    except Exception:
        return []
    host = (urlparse(base).hostname or "").replace("www.", "")
    paginas = []
    for href, rotulo in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', home, re.I | re.S):
        completo = urljoin(base, href).split("?")[0]
        if (urlparse(completo).hostname or "").replace("www.", "") != host:
            continue
        rotulo = html.unescape(re.sub(r"<[^>]+>", " ", rotulo))
        if PAGINA_DE_MARCAS.search(urlparse(completo).path) or re.search(r"(?i)\bmarcas\b", rotulo):
            if completo not in paginas:
                paginas.append(completo)
    proprio = {_compacto(p) for p in palavras_chave(cliente) if len(p) >= 3} | {_compacto(cliente)}
    for url in paginas[:3]:
        try:
            pagina = requests.get(url, headers=cabecalho, timeout=15).text
        except Exception:
            continue
        texto = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", pagina))).split())
        if not re.search(r"(?i)\bmarcas?\b", texto):
            continue
        nomes = []
        for src in re.findall(r'(?:src|srcSet|srcset)="([^"]+)"', pagina):
            for parte in src.split(","):
                arquivo = unquote(parte.strip().split(" ")[0].split("?")[0].rsplit("/", 1)[-1])
                if not re.search(r"(?i)\.(png|svg|webp|jpe?g|avif)$", arquivo) or "~mv2" in arquivo \
                        or re.match(r"^[0-9a-f]{6}_", arquivo):
                    continue
                nome = re.sub(r"(?i)\.(png|svg|webp|jpe?g|avif)$", "", arquivo)
                nome = re.sub(r"(?i)\b(logo|logotipo|marca|final|novo|nova|site|\d+x\d+)\b", " ", nome)
                nome = " ".join(re.sub(r"[^A-Za-zÀ-ú0-9 ]", " ", nome.replace("_", " ").replace("-", " ")).split())
                if not 3 <= len(nome) <= 25 or nome.isdigit() or NOME_NAO_E_MARCA.match(nome):
                    continue
                if _compacto(nome) in proprio or any(p and p in _compacto(nome) for p in proprio if len(p) >= 5):
                    continue
                for tamanho in (3, 2, 1):
                    palavras = texto.split()
                    achado = next((" ".join(palavras[i:i + tamanho]).strip(",.;:") for i in range(len(palavras) - tamanho + 1)
                                   if _compacto(" ".join(palavras[i:i + tamanho])) == _compacto(nome)), None)
                    if achado:
                        nome = achado
                        break
                if _compacto(nome) not in [_compacto(n) for n in nomes]:
                    nomes.append(nome)
        if 2 <= len(nomes) <= 15:
            evento("extracao", f"marcas que o cliente trabalha (página {url}): {', '.join(nomes)}")
            return nomes
    return []


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
    registro = ler_mercado_livre(url) if MERCADO_LIVRE.search(url) else _ler_pagina_com_foto(url)
    if not registro or not registro.get("name") or CAPTCHA.search(registro.get("name") or "") or CAPTCHA.search(registro.get("description") or ""):
        return None
    registro.setdefault("url", url)
    registro["url"] = registro.get("url") or url
    registro.setdefault("image", "")
    return registro


def buscar_google_gemini(consulta, limite=12):
    """Links de páginas vindos da busca do Google feita pelo Gemini (ferramenta google_search).
    O modelo só devolve ENDEREÇOS de resultado; cada página é lida e conferida depois,
    como qualquer outro resultado de busca. Sem chave ou com erro, devolve []."""
    import requests
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        return []
    pedido = {"contents": [{"role": "user", "parts": [{"text":
              f"Pesquise no Google páginas de lojas online brasileiras que vendem produtos de: {consulta}. "
              "Quero páginas de PRODUTO (uma por produto), não notícias nem redes sociais. "
              "Liste os endereços encontrados."}]}],
              "tools": [{"google_search": {}}],
              "generationConfig": {"temperature": 0}}
    for modelo in (MODELO_SELECAO,) + MODELOS_RESERVA:
        try:
            r = requests.post(GEMINI_URL.format(modelo=modelo), json=pedido,
                              headers={"x-goog-api-key": chave}, timeout=max(10, min(45, restante() - 15)))
        except requests.RequestException:
            continue
        if r.status_code in (429, 500, 503):
            continue
        if r.status_code != 200:
            evento("extracao", f"busca Google via {modelo} recusada (HTTP {r.status_code})", "aviso")
            return []
        break
    else:
        evento("extracao", "busca Google via Gemini sem cota agora (HTTP 429); seguindo sem ela", "aviso")
        return []
    dados = r.json()
    brutos = []
    for cand in dados.get("candidates") or []:
        meta = cand.get("groundingMetadata") or {}
        for bloco in meta.get("groundingChunks") or []:
            uri = (bloco.get("web") or {}).get("uri")
            if uri and uri not in brutos:
                brutos.append(uri)
        texto = " ".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [])
        for uri in re.findall(r"https?://[^\s)\]>\"']+", texto):
            if uri not in brutos and "vertexaisearch" not in uri:
                brutos.append(uri.rstrip(".,;"))

    def resolver(uri):
        if "grounding-api-redirect" not in uri:
            return uri
        try:
            return requests.get(uri, headers={"User-Agent": "Mozilla/5.0"}, timeout=20,
                                allow_redirects=True, stream=True).url
        except requests.RequestException:
            return None
    with ThreadPoolExecutor(8) as pool:
        urls = [u for u in pool.map(resolver, brutos[:limite * 2]) if u]
    saida = []
    for u in urls:
        if u not in saida and not re.search(r"instagram|facebook|youtube|tiktok|wikipedia|linkedin", u, re.I):
            saida.append(u)
    return saida[:limite]


PRODUTO_NA_URL = re.compile(r"/p$|/p/|/produto|/product|/dp/|MLB-?\d|\d{4,}|-[a-z0-9]+-[a-z0-9]+-[a-z0-9]+-[a-z0-9]+", re.I)
NAO_E_PRODUTO = re.compile(r"(?i)/(blog|conta|login|carrinho|cart|checkout|categoria|category|busca|search|politica|"
                           r"atendimento|institucional|ajuda|marca|marcas|lista)(/|$)|\.(css|js|png|jpe?g|svg|webp)$")


def links_de_produto(url, chaves, limite=8):
    """Página de categoria de loja (leroymerlin.com.br/lampadas-de-led): devolve links de
    produto do mesmo site cujo endereço cite as palavras do tipo buscado."""
    import requests
    from urllib.parse import urljoin
    try:
        pagina = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/128 Safari/537.36"}, timeout=12).text
    except requests.RequestException:
        return []
    host = urlparse(url).hostname or ""
    saida = []
    for href in re.findall(r'href="([^"#]+)"', pagina):
        completo = urljoin(url, href).split("?")[0]
        alvo = urlparse(completo)
        caminho = sem_acento(alvo.path)
        if (alvo.hostname or "").replace("www.", "") != host.replace("www.", "") and "mercadolivre" not in (alvo.hostname or ""):
            continue
        if completo in saida or completo.rstrip("/") == url.rstrip("/") or NAO_E_PRODUTO.search(alvo.path):
            continue
        if not PRODUTO_NA_URL.search(alvo.path) or not any(c in caminho for c in chaves):
            continue
        saida.append(completo)
        if len(saida) >= limite:
            break
    return saida


def links_da_marca(url, marca, limite=12):
    """Página de loja que lista vários produtos da marca (super.angeloni.com.br/bonfiore):
    devolve os links de produto que citam a marca no endereço."""
    import requests
    from urllib.parse import urljoin
    try:
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12).text
    except requests.RequestException:
        return []
    saida, vistos = [], {url}
    for href in re.findall(r'href="([^"#?]+)"', html):
        completo = urljoin(url, href)
        caminho = sem_acento(urlparse(completo).path)
        if completo in vistos or not any(m in caminho for m in marca):
            continue
        if len(caminho.strip("/").split("/")[-1]) < 12 and not caminho.endswith("/p"):
            continue
        vistos.add(completo)
        saida.append(completo)
        if len(saida) >= limite:
            break
    return saida


def assunto_dos_achados(achados, marca):
    """Palavra que mais aparece nos nomes achados, fora a marca ("queijo")."""
    contagem = {}
    for c in achados:
        for palavra in set(palavras_chave(c.get("nome") or "")):
            if len(palavra) >= 4 and palavra not in marca and not palavra.isdigit():
                contagem[palavra] = contagem.get(palavra, 0) + 1
    return max(contagem.items(), key=lambda kv: kv[1])[0] if contagem else ""


PAGINA_NAO_E_LOJA = re.compile(
    r"(?i)(\.gov\.br|\.jus\.br|\.leg\.br|banco|bank|bradesco|itau|santander|caixa\.gov|nubank|serasa|"
    r"reclameaqui|wikipedia|jusbrasil|linkedin|glassdoor|indeed|vagas|youtube|facebook|instagram|tiktok|"
    r"folheto|encarte|tiendeo|ofertasdodia|cupom|cupons|noticia|g1\.globo|infomoney|valor\.globo|"
    r"exame\.com|estadao|uol\.com\.br/noticias|/blog/|/vagas|/trabalhe)")


def buscar_candidatos_web(cliente, segmento, categorias, site, nomes=(), limite=24, foco="", tipos=()):
    """Busca na web por termos do próprio site. Página de outra marca vira candidato
    [busca]; o modelo marca do_cliente e o pedido fica com produtos_similares."""
    host = urlparse(normalizar_site(site)).hostname or ""
    pares, vistos = [], set()
    termos = termos_de_busca(cliente, segmento, categorias, nomes, foco)
    tipos = tipos_uteis(tipos)
    marcas = list(MARCAS["lista"])
    revenda = bool(tipos) and not foco and not marcas
    if revenda:
        termos = list(dict.fromkeys([f"{t} comprar" for t in tipos[:4]]))
    if marcas:
        termos = [f"{m} {tipos[i % len(tipos)]}" if tipos else f"{m} comprar" for i, m in enumerate(marcas[:6])]
        evento("extracao", "buscando só produtos das marcas que o cliente trabalha: " + ", ".join(marcas))
    termos = termos[:6] if marcas else termos[:4]
    evento("extracao", "termos de busca (em paralelo): " + " · ".join(termos))
    resultados = [r or [] for r in em_paralelo(buscar_na_web, termos, len(termos) or 1, teto=75)]
    for termo, urls in zip(termos, resultados):
        for url in urls:
            if url not in vistos and host not in url and not PAGINA_NAO_E_LOJA.search(url):
                vistos.add(url)
                pares.append((url, termo))
    pares = pares[:limite]
    marca = [] if revenda else [p for p in palavras_chave(cliente) if len(p) >= 4]
    if marcas:
        marca = list(dict.fromkeys(v for m in marcas for v in (_compacto(m), "-".join(re.findall(r"[a-z0-9]+", sem_acento(m))))
                                   if len(v) >= 4))
    if revenda:
        evento("extracao", "distribuidor sem marca própria: buscando produtos dos tipos que ele vende, de qualquer marca")
    achados, fora, lidas = [], 0, set()

    def ler(lista, frouxo=False):
        nonlocal fora
        lista = [(u, t) for u, t in lista if u not in lidas]
        lidas.update(u for u, _ in lista)
        if not lista or restante() < 15:
            return
        registros = em_paralelo(_ler_pagina_busca, [u for u, _ in lista])
        nomes_vistos = {(sem_acento(c["nome"]), c["imagem"]) for c in achados}
        for (url, termo), r in zip(lista, registros):
            if not r:
                continue
            chaves_termo = [c[:5] for c in palavras_chave(termo) if c not in ("comprar",) and len(c) >= 3]
            aceito = (cita_marca(r["name"], marcas) if marcas
                      else any(c in sem_acento(r["name"]) for c in chaves_termo) if frouxo
                      else relevante(r["name"], termo, cliente, r.get("url") or url))
            if not aceito:
                fora += 1
                continue
            chave = (sem_acento(r["name"]), r.get("image"))
            if chave in nomes_vistos:
                continue
            nomes_vistos.add(chave)
            achados.append(candidato(r["name"], r["url"], r["image"], r.get("price"), r.get("category"),
                                     r.get("description"), "busca"))

    ler(pares, frouxo=revenda)

    def falta(segundos):
        if len(achados) >= 12:
            return False
        if restante() < segundos:
            evento("extracao", f"busca na web encerrada pelo prazo com {len(achados)} produtos", "aviso")
            PRAZO["avisado"] = True
            return False
        return True

    if falta(40) and tipos:
        extras = []
        tarefas = []
        for url, termo in pares[:12]:
            chaves = [c[:5] for c in palavras_chave(termo) if c not in palavras_chave(cliente) and len(c) >= 3]
            if chaves:
                tarefas.append((url, termo, chaves))
        for (url, termo, _), links in zip(tarefas, em_paralelo(lambda t: links_de_produto(t[0], t[2]), tarefas, teto=15)):
            extras += [(link, termo) for link in (links or []) if host not in link]
        extras = [e for e in dict.fromkeys(extras) if e[0] not in lidas]
        if extras:
            evento("extracao", f"busca na web: {len(extras)} produtos dentro de páginas de categoria das lojas")
            ler(extras[:40], frouxo=True)
    if falta(40) and marca:
        listas = [(u, t) for u, t in pares if any(m in sem_acento(urlparse(u).path) for m in marca)]
        extras = []
        for (url, termo), links in zip(listas[:4], em_paralelo(lambda t: links_da_marca(t[0], marca), listas[:4], teto=15)):
            extras += [(link, termo) for link in (links or []) if host not in link]
        if extras:
            evento("extracao", f"busca na web: {len(extras)} links de produto da marca em páginas de loja")
            ler(extras[:24])
    if falta(60) and marca:
        assunto = assunto_dos_achados(achados, marca)
        if assunto:
            termo = f"{assunto} {cliente.split()[0]}"
            evento("extracao", f"busca na web: nova busca por {termo}")
            novos = [(u, f"{cliente}") for u in buscar_na_web(termo) if host not in u and u not in lidas]
            ler(novos[:12])
            listas = [(u, t) for u, t in novos if any(m in sem_acento(urlparse(u).path) for m in marca)]
            extras = []
            for (url, t), links in zip(listas[:3], em_paralelo(lambda x: links_da_marca(x[0], marca), listas[:3], teto=15)):
                extras += [(link, t) for link in (links or []) if host not in link]
            ler(extras[:24])
    if falta(40) and marca:
        lojas = []
        for c in list(achados) + [{"url": u} for u, _ in pares]:
            h = urlparse(c.get("url") or "").hostname or ""
            if h and h != host and h not in lojas and "mercadolivre" not in h:
                lojas.append(h)
        slugs = list(dict.fromkeys(["-".join(marca)] + marca))
        extras = []
        paginas = [f"https://{h}/{sl}" for h in lojas[:6] for sl in slugs] + \
                  [f"https://{h}/busca?q={sl}" for h in lojas[:6] for sl in slugs]
        for links in em_paralelo(lambda u: links_da_marca(u, marca), paginas, teto=15):
            extras += [(link, cliente) for link in (links or []) if host not in link]
        extras = [e for e in dict.fromkeys(extras) if e[0] not in lidas]
        if extras:
            evento("extracao", f"busca na web: {len(extras)} links da marca nas lojas {', '.join(lojas[:6])}")
            ler(extras[:30])
    if falta(60) and marca:
        termo = f"{cliente} {assunto_dos_achados(achados, marca) or segmento or ''}".strip()
        google = [u for u in buscar_google_gemini(termo) if host not in u and u not in lidas]
        evento("extracao", f"busca no Google (via {MODELO_SELECAO}): {len(google)} páginas para {termo}")
        ler([(u, cliente) for u in google])
        listas = [u for u in google if any(m in sem_acento(urlparse(u).path) for m in marca)]
        extras = []
        for links in em_paralelo(lambda u: links_da_marca(u, marca), listas[:3], teto=15):
            extras += [(link, cliente) for link in (links or []) if host not in link]
        ler(extras[:24])
    evento("extracao", f"busca na web: {len(achados)} produtos em {len(lidas)} páginas "
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


def _descobrir_pelo_barroso(cliente, site, perfil, do_site):
    """barroso-chat com busca na web: site oficial, tipos de produto e segmento.
    Sem chave, sem resposta ou sem tipos úteis, devolve None e o Gemini assume."""
    import requests
    chave = os.environ.get("BARROSO_API_KEY", "").strip()
    if not chave or BARROSO_FORA["sim"]:
        return None
    pergunta = (f"Pesquise na web a empresa brasileira {cliente}{perfil}" + (f", site {site}" if site else "") + ". "
                + (f"O site dela diz: {do_site}. Os tipos de produto têm que bater com esse texto. " if do_site else "")
                + "Responda SOMENTE um JSON: {\"site_oficial\": \"https://... ou vazio\", "
                "\"tipos_de_produto\": [\"3 a 5 produtos CONCRETOS que ela vende, como um comprador digitaria numa loja "
                "online (ex.: 'arroz tipo 1 5kg', 'detergente líquido 500ml', 'dipirona 500mg'); nunca categoria "
                "ampla como 'alimentos básicos', 'bebidas', 'ofertas' ou 'melhores produtos'\"], "
                "\"segmento\": \"ramo em poucas palavras\"}. site_oficial não pode ser rede social nem marketplace.")
    pedido = {"model": MODELO_BUSCA, "tools": [{"type": "web_search"}], "input": pergunta}
    try:
        r = requests.post(BARROSO_URL, json=pedido, headers={"Authorization": "Bearer " + chave},
                          timeout=max(15, min(60, restante() - 20)))
    except requests.RequestException as erro:
        evento("extracao", f"descoberta da empresa via barroso-chat fora do ar ({type(erro).__name__})", "aviso")
        return None
    if r.status_code != 200:
        evento("extracao", f"descoberta da empresa via barroso-chat: HTTP {r.status_code}", "aviso")
        return None
    corpo = r.json() or {}
    texto = corpo.get("output_text") or ""
    if not texto:
        for item in corpo.get("output") or []:
            for parte in item.get("content") or []:
                texto += (parte.get("text") or "") + "\n"
    custo = corpo.get("cost")
    registrar_modelo(MODELO_BUSCA, custo if isinstance(custo, (int, float)) else 0)
    try:
        dados = _texto_json(texto)
    except ValueError:
        evento("extracao", "descoberta da empresa via barroso-chat: resposta sem JSON", "aviso")
        return None
    tipos = tipos_uteis(dados.get("tipos_de_produto") or [])
    if not tipos:
        return None
    oficial = str(dados.get("site_oficial") or "").strip()
    if oficial and (re.search(r"instagram|facebook|linktr|wa\.me|whatsapp|mercadolivre|shopee|amazon", oficial, re.I)
                    or not oficial.startswith("http")):
        oficial = ""
    evento("extracao", f"descoberta da empresa via barroso-chat: {json.dumps(dados, ensure_ascii=False)[:400]}")
    return {"site_oficial": oficial or _site_pelo_perfil(site, cliente), "tipos": tipos,
            "segmento": str(dados.get("segmento") or "").strip()}


def descobrir_empresa(cliente, site=""):
    """Instagram ou site sem catálogo: pergunta ao Google (via Gemini) qual é o site oficial
    da empresa e que tipos de produto ela vende. Só ENDEREÇOS e TIPOS voltam; os produtos
    continuam vindo das páginas lidas e conferidas. Sem chave ou com erro, devolve {}."""
    import requests
    perfil = ""
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", site or "")
    if m:
        perfil = f" (Instagram @{m.group(1)})"
    do_site = texto_do_site(site)
    pelo_barroso = _descobrir_pelo_barroso(cliente, site, perfil, do_site)
    if pelo_barroso:
        return pelo_barroso
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        return _descobrir_sem_google(cliente, site)
    pergunta = (f"Pesquise no Google a empresa brasileira {cliente}{perfil}. "
                + (f"O site dela diz: {do_site}. Os tipos de produto têm que bater com esse texto. " if do_site else "")
                + 
                "Responda SOMENTE um JSON: {\"site_oficial\": \"https://... ou vazio\", "
                "\"tipos_de_produto\": [\"3 a 5 tipos de produto que ela vende, 2 a 4 palavras cada\"], "
                "\"segmento\": \"ramo em poucas palavras\"}. site_oficial não pode ser rede social nem marketplace.")
    pedido = {"contents": [{"role": "user", "parts": [{"text": pergunta}]}],
              "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0}}
    for modelo in (MODELO_SELECAO,) + MODELOS_RESERVA:
        try:
            r = requests.post(GEMINI_URL.format(modelo=modelo), json=pedido,
                              headers={"x-goog-api-key": chave}, timeout=max(10, min(40, restante() - 20)))
        except requests.RequestException:
            continue
        if r.status_code != 200:
            evento("extracao", f"descoberta da empresa via {modelo}: HTTP {r.status_code} {r.text[:200]}", "aviso")
            continue
        texto = " ".join(pt.get("text", "") for c in r.json().get("candidates") or []
                         for pt in (c.get("content") or {}).get("parts") or [])
        achado = re.search(r"\{.*\}", texto, re.S)
        if not achado:
            evento("extracao", f"descoberta da empresa via {modelo}: resposta sem JSON: {texto[:300]}", "aviso")
            continue
        try:
            dados = json.loads(achado.group(0))
        except ValueError:
            continue
        oficial = str(dados.get("site_oficial") or "").strip()
        if oficial and (re.search(r"instagram|facebook|linktr|wa\.me|whatsapp|mercadolivre|shopee|amazon", oficial, re.I)
                        or not oficial.startswith("http")):
            oficial = ""
        tipos = tipos_uteis(dados.get("tipos_de_produto") or []) or list(BARROSO_INFO["tipos"])
        evento("extracao", f"descoberta da empresa via {modelo}: {json.dumps(dados, ensure_ascii=False)[:400]}")
        return {"site_oficial": oficial or _site_pelo_perfil(site, cliente), "tipos": tipos,
                "segmento": str(dados.get("segmento") or "").strip()}
    return _descobrir_sem_google(cliente, site)


def _nome_no_instagram(site):
    """Nome da empresa no Instagram. Link de post (/p/...) é lido como está: o título do post
    traz o nome do perfil ("P2 Distribuidor - UAI SALGADOS on Instagram") e o @."""
    import requests
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", site or "")
    if not m:
        return ""
    url = site if m.group(1) in ("p", "reel", "reels", "tv") else f"https://www.instagram.com/{m.group(1)}/"
    try:
        r = requests.get(url, headers={"User-Agent": "facebookexternalhit/1.1"}, timeout=15)
    except Exception:
        return ""
    partes = []
    t = re.search(r'<meta property="og:title" content="([^"]+)"', r.text)
    if t:
        partes.append(re.sub(r"\s+on Instagram.*$", "", html.unescape(t.group(1)).split("(")[0]).strip())
    d = re.search(r'<meta (?:property="og:description"|name="description") content="[^"]*?- ([A-Za-z0-9._]+) on ', r.text)
    if d:
        partes.append("@" + d.group(1))
    return " ".join(p for p in partes if p)


def _titulo_cita(pagina, cliente):
    """O título ou o nome do site tem que trazer o nome do cliente inteiro (focoled.com é "Mundo Lucido")."""
    partes = re.findall(r"<title[^>]*>([^<]*)|og:site_name\" content=\"([^\"]*)", pagina[:20000], re.I)
    alvo = re.sub(r"[^a-z0-9]", "", sem_acento(" ".join(a + b for a, b in partes)))
    nome = re.sub(r"[^a-z0-9]", "", sem_acento(cliente))
    return bool(nome) and nome in alvo


def _site_pelo_perfil(site, cliente=""):
    """Domínios prováveis a partir do @ (focoledoficial -> focoled.com.br). Site em
    manutenção ou sem página não conta."""
    import requests
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", site or "")
    if not m:
        return ""
    base = re.sub(r"[._]", "", m.group(1).lower())
    raizes = list(dict.fromkeys([base, re.sub(r"(oficial|official|loja|store|br)$", "", base),
                                 re.sub(r"^(loja|use|sou)", "", base)]))
    for raiz in raizes:
        for dominio in (f"{raiz}.com.br", f"www.{raiz}.com.br", f"{raiz}.com"):
            try:
                r = requests.get(f"https://{dominio}/", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            except Exception:
                continue
            if r.status_code == 200 and len(r.text) > 3000 and not re.search(
                    r"(?i)manuten[cç][aã]o|em breve|coming soon|parked|domain for sale", r.text[:6000]) \
                    and _titulo_cita(r.text, cliente or raiz):
                evento("extracao", f"site achado pelo @ do perfil: {r.url}")
                return r.url
    return ""


TEXTO_DO_SITE = {}


def texto_do_site(site, limite=1500):
    """Título, descrição e títulos da home: o que a própria empresa diz que vende."""
    if site not in TEXTO_DO_SITE:
        TEXTO_DO_SITE[site] = _ler_texto_do_site(site, limite)
    return TEXTO_DO_SITE[site]


def _ler_texto_do_site(site, limite):
    import requests
    if not site or re.search(r"instagram\.com/|facebook\.com/|linktr\.ee/", site):
        return ""
    try:
        pagina = requests.get(normalizar_site(site), headers={"User-Agent": "Mozilla/5.0"}, timeout=15).text
    except Exception:
        return ""
    partes = re.findall(r"<title[^>]*>([^<]*)</title>", pagina, re.I)[:1]
    partes += re.findall(r'<meta[^>]+(?:name="description"|property="og:description")[^>]+content="([^"]*)"', pagina, re.I)[:2]
    partes += re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", pagina, re.I | re.S)[:25]
    limpas = []
    for t in partes:
        t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split())
        if len(t) >= 4 and t not in limpas:
            limpas.append(t)
    return " | ".join(limpas)[:limite]


def _descobrir_sem_google(cliente, site):
    """Cota do Google esgotada: a fila de IAs gratuitas diz que TIPOS de produto uma empresa
    com esse nome e perfil vende. Só termos de busca; produto, foto e preço continuam vindo
    das páginas lidas."""
    nome = _nome_no_instagram(site)
    oficial = _site_pelo_perfil(site, cliente)
    do_site = texto_do_site(site)
    if do_site:
        evento("extracao", f"lendo o que o próprio site diz que vende: {do_site[:200]}")
    pergunta = (f"Empresa brasileira: {cliente}. Nome no perfil: {nome or cliente}. Perfil: {site or '-'}. "
                + (f"Texto do site da empresa (título, descrição e títulos): {do_site}. "
                   "Diga que tipos de produto ela vende USANDO SÓ o que esse texto diz; nunca deduza pelo "
                   "nome da empresa (ex.: 'Logiscal' não é software de logística se o site fala de paletes). "
                   if do_site else
                   "Pelo nome e pelo @ do perfil, diga que tipos de produto ela provavelmente vende "
                   "(ex.: 'uaisalgados' = salgados). ")
                + "Responda SOMENTE JSON: "
                "{\"tipos_de_produto\": [\"3 a 5 tipos, 2 a 4 palavras cada, termos que um comprador "
                "digitaria numa loja online\"], \"segmento\": \"ramo em poucas palavras\"}")
    try:
        dados, _ = _chamar_openrouter([{"role": "user", "content": pergunta}])
    except Exception as erro:
        evento("extracao", f"descoberta sem Google falhou: {type(erro).__name__}: {str(erro)[:200]}", "aviso")
        return {"site_oficial": oficial, "tipos": [], "segmento": ""}
    tipos = tipos_uteis((dados or {}).get("tipos_de_produto") or [])
    if not tipos and BARROSO_INFO["tipos"]:
        tipos = list(BARROSO_INFO["tipos"])
        evento("extracao", "tipos genéricos na descoberta; usando os tipos que a pesquisa na web descreveu")
    evento("extracao", f"descoberta sem Google (fila de IAs): {', '.join(tipos) or 'nada'}")
    return {"site_oficial": oficial, "tipos": tipos, "segmento": str((dados or {}).get("segmento") or "").strip()}

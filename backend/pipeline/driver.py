"""Ponte entre a funcao da pipeline e o repositorio zydon-criar-pocs.

Chamado pela funcao JS `pipeline_poc`, sempre com o repositorio ja baixado no
commit fixado em ZYDON_REPO:

    python3 driver.py <acao> entrada.json saida.json

Nao reescreve nada do repositorio: importa `extracao`, `atendimento`,
`subir_banners` e `segmento` e chama as mesmas funcoes que o receptor chamava.
Cada linha `EVENTO {...}` no stdout vira um registro em `pedido_eventos`.
O banco e a unica memoria entre execucoes; o que precisa sobreviver (logo e
pasta dos banners) volta em `arquivos` e e restaurado na execucao seguinte.
"""

import base64
import io
import json
import os
import re
import sys
import tarfile
import traceback
import unicodedata
from pathlib import Path

REPO = Path(os.environ["ZYDON_REPO"])
for _p in (REPO, REPO / "Identidade Visual", REPO / "Criar Portais", REPO / "POC Completa"):
    sys.path.insert(0, str(_p))

import selecao  # noqa: E402

ORG = "pocs"
TRABALHO = Path(os.environ.get("ZYDON_TRABALHO", "/tmp/pocs"))

ROTULOS_RAMO = (
    "alimentos e bebidas",
    "autopeças",
    "materiais elétricos e industriais",
    "saúde e produtos hospitalares",
    "cosméticos e beleza",
    "materiais de construção",
    "tecnologia e informática",
    "segurança eletrônica",
    "distribuição e logística",
)


def evento(etapa, mensagem, nivel="info"):
    print("EVENTO " + json.dumps({"etapa": etapa, "mensagem": str(mensagem)[:1500],
                                  "nivel": nivel}, ensure_ascii=False), flush=True)


def _sem_acento(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def nome_arquivo(empresa, pedido_id):
    limpo = "".join(c if c.isalnum() else "_" for c in (empresa or pedido_id or "cliente").lower())
    limpo = "_".join(p for p in limpo.split("_") if p) or "cliente"
    return f"{limpo}_poc.json"


def pasta_pedido(pedido_id):
    alvo = TRABALHO / re.sub(r"[^A-Za-z0-9_-]", "_", pedido_id)
    alvo.mkdir(parents=True, exist_ok=True)
    return alvo


def empacotar(pasta):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.add(str(pasta), arcname=Path(pasta).name)
    return base64.b64encode(buffer.getvalue()).decode()


def desempacotar(conteudo_b64, destino):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(conteudo_b64)), mode="r:gz") as tar:
        raiz = tar.getnames()[0].split("/")[0]
        tar.extractall(str(destino), filter="data")
    return destino / raiz


def previa_jpeg(caminho, largura=960):
    from PIL import Image
    with Image.open(caminho) as img:
        img = img.convert("RGBA")
        fundo = Image.new("RGB", img.size, (255, 255, 255))
        fundo.paste(img, mask=img.split()[3])
        if fundo.width > largura:
            fundo = fundo.resize((largura, round(fundo.height * largura / fundo.width)))
        saida = io.BytesIO()
        fundo.save(saida, "JPEG", quality=82)
    return base64.b64encode(saida.getvalue()).decode()


def cor_da_pasta(pasta):
    try:
        dados = json.loads((Path(pasta) / "paleta.json").read_text(encoding="utf-8"))
        return dados.get("marca") or dados.get("principal")
    except (OSError, ValueError):
        return None


def pecas_para_tela(pasta, quais=None):
    import subir_banners
    pecas, _ = subir_banners.pecas_da_pasta(pasta, quais)
    return {chave: {"previa_base64": previa_jpeg(caminho),
                    "dimensao": list(subir_banners.DESTINOS[chave]["dimensao"])}
            for chave, caminho in pecas.items()}


def restaurar_logo(entrada, pasta):
    logo = entrada.get("logo")
    if not logo:
        return None
    alvo = pasta / logo["nome"]
    alvo.write_bytes(base64.b64decode(logo["conteudo_base64"]))
    return alvo


def restaurar_banners(entrada, pasta):
    conteudo = entrada.get("banners_tar")
    if not conteudo:
        return None
    return desempacotar(conteudo, pasta / "banners")


def gravar_catalogo(catalogo, pedido_id):
    import atendimento
    caminho = atendimento.DESTINO_JSON / nome_arquivo(catalogo.get("empresa"), pedido_id)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def inferir_segmento(texto):
    """(segmento, criterio). Nunca vazio: sem sinal nenhum, diz que nao achou."""
    import segmento as mod_segmento
    base = _sem_acento(texto)
    palavras = set(re.findall(r"[a-z]{4,}", base))
    melhor, pontos = None, 0
    for chave in mod_segmento._ler_cache():
        termos = {t for t in chave.split("-") if len(t) > 3}
        acertos = sum(1 for t in termos if any(p.startswith(t[:6]) for p in palavras))
        if acertos > pontos and acertos >= 2:
            melhor, pontos = chave.replace("-", " "), acertos
    if melhor:
        return melhor, f"cache_segmentos ({pontos} termos)"
    contagem = []
    for indice, (radicais, _) in enumerate(mod_segmento.AMBIENTES):
        contagem.append((sum(base.count(r) for r in radicais), indice))
    total, indice = max(contagem)
    if total:
        return ROTULOS_RAMO[indice], f"palavras-chave do ramo ({total} ocorrencias)"
    nomes = [p for p in re.findall(r"[a-zà-ú]{4,}", texto.lower()) if p not in {"para", "com", "kit"}]
    if nomes:
        comum = max(set(nomes), key=nomes.count)
        return f"produtos de {comum}", "palavra mais frequente nos nomes dos produtos"
    return "catálogo variado", "sem sinal de ramo nos produtos"


SEGMENTO_GENERICO = re.compile(
    r"^(distribui[cç][aã]o|com[eé]rcio|varejo|atacado|revenda|loja|b2b|vendas?|ind[uú]stria)"
    r"(\s+(b2b|geral|em geral|atacadista|varejista|de produtos))*$", re.I)


def segmento_do_modelo(texto):
    """(segmento, criterio) com o que o cliente vende, dito pelo modelo; ("", None) se genérico."""
    texto = re.sub(r"\s+", " ", str(texto or "")).strip(" .;:-").lower()
    texto = re.sub(r"^(distribui[cç][aã]o|com[eé]rcio|venda|atacado|revenda) (b2b )?de ", "", texto)
    if not texto or len(texto) > 60 or SEGMENTO_GENERICO.match(texto):
        return "", None
    return texto, "descrito pelo modelo a partir dos produtos escolhidos"


def svg_para_png(caminho_svg, lado=1024):
    """SVG -> PNG com alfa de verdade. O rasterizador do repo pinta sobre branco e
    depois tira o fundo branco: logo branca (Fast Shop) some inteira. Aqui o alfa sai
    do próprio desenho (cairosvg, que entende máscara e recorte rotacionado; svglib
    renderizado em fundo branco e preto como reserva)."""
    import numpy as np
    from PIL import Image
    destino = Path(caminho_svg).with_suffix(".png")
    try:
        import cairosvg
        cairosvg.svg2png(url=str(caminho_svg), write_to=str(destino), output_width=lado)
        img = Image.open(destino).convert("RGBA")
    except Exception as erro_cairo:
        from reportlab.graphics import renderPM
        from svglib.svglib import svg2rlg

        def render(fundo):
            desenho = svg2rlg(str(caminho_svg))
            if desenho is None or not desenho.width or not desenho.height:
                raise ValueError(f"SVG vazio ou inválido (cairosvg: {erro_cairo})")
            fator = lado / max(desenho.width, desenho.height)
            desenho.width *= fator
            desenho.height *= fator
            desenho.scale(fator, fator)
            return np.asarray(renderPM.drawToPIL(desenho, dpi=72, bg=fundo).convert("RGB"), dtype=np.float32)
        branco, preto = render(0xFFFFFF), render(0x000000)
        alfa = np.clip(1 - (branco - preto).mean(axis=2) / 255.0, 0, 1)
        cor = np.clip(np.where(alfa[..., None] > 0.01, preto / np.maximum(alfa[..., None], 1e-3), 0), 0, 255)
        img = Image.fromarray(np.dstack([cor, alfa * 255]).astype(np.uint8), "RGBA")
    if img.getchannel("A").getbbox() is None:
        raise ValueError("o SVG não desenha nada visível")
    img.save(destino, "PNG")
    return destino


def logo_clara(caminho):
    """True quando a parte visível da logo é quase toda branca (some no fundo branco)."""
    import numpy as np
    from PIL import Image
    img = np.asarray(Image.open(caminho).convert("RGBA"), dtype=np.float32)
    visivel = img[..., 3] > 128
    if not visivel.any():
        return False
    return float((img[..., :3][visivel] @ np.array([0.299, 0.587, 0.114])).mean()) > 215


def conferir_logo(logo):
    """(logo_utilizavel, observacao). Toda logo passa pela régua do repo
    (logo.normalizar com a régua do portal); SVG vira PNG com alfa antes.
    Logo que não passa não segue calada: volta o motivo para as observações."""
    if not logo:
        return None, None
    try:
        import logo as mod_logo
        import regua as mod_regua
        caminho = Path(logo)
        if caminho.suffix.lower() == ".svg":
            caminho = svg_para_png(caminho)
        caminho = Path(recortar_circulo_de_perfil(caminho))
        limiares = mod_regua.carregar()
        regua_logo = {**limiares["logo"], **limiares.get("logo_portal", {})}
        try:
            mod_logo.normalizar(caminho, regua_logo)
        except Exception as erro:
            if "pequena demais" not in str(erro):
                raise
            from PIL import Image
            img = Image.open(caminho).convert("RGBA")
            fator = max(2, -(-400 // max(img.size)))
            img = img.resize((img.width * fator, img.height * fator), Image.LANCZOS)
            caminho = caminho.with_name(caminho.stem + "_ampliada.png")
            img.save(caminho, "PNG")
            mod_logo.normalizar(caminho, regua_logo)
            evento("extracao", f"logo pequena (foto de perfil) ampliada para {img.width}x{img.height}")
        return str(caminho), None
    except Exception as erro:
        return None, (f"a logo achada ({Path(str(logo)).name}) não foi usada: {type(erro).__name__}: {erro}")


def recortar_circulo_de_perfil(caminho):
    """Foto de perfil redonda salva com cantos pretos (ou de outra cor sólida): tudo fora do
    círculo vira transparente, senão os cantos entram no banner e a logo sai preta.
    Devolve o caminho novo (PNG) ou o mesmo caminho quando não é esse caso."""
    from PIL import Image, ImageDraw
    try:
        img = Image.open(caminho).convert("RGBA")
    except Exception:
        return caminho
    w, h = img.size
    if abs(w - h) > max(2, w * 0.03):
        return caminho
    cantos = [img.getpixel(p)[:3] for p in [(1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)]]
    base = cantos[0]
    iguais = all(max(abs(a - b) for a, b in zip(c, base)) < 30 for c in cantos)
    dentro = img.getpixel((w // 2, max(2, h // 12)))[:3]
    if not iguais or max(abs(a - b) for a, b in zip(dentro, base)) < 60:
        return caminho
    mascara = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mascara).ellipse((1, 1, w - 2, h - 2), fill=255)
    alfa = Image.composite(img.getchannel("A"), Image.new("L", (w, h), 0), mascara)
    img.putalpha(alfa)
    alvo = Path(caminho).with_name(Path(caminho).stem + "_circulo.png")
    img.save(alvo, "PNG")
    evento("extracao", "foto de perfil redonda: cantos fora do círculo removidos")
    return alvo


def foto_de_perfil_como_logo(caminho, lado=600):
    """Foto de perfil do Instagram usada como está: só ampliada para PNG quadrado.
    É a logo real do cliente; inventar logo de texto é pior que usar a foto pequena."""
    from PIL import Image
    img = Image.open(recortar_circulo_de_perfil(caminho)).convert("RGBA")
    if max(img.size) < lado:
        fator = lado / max(img.size)
        img = img.resize((round(img.width * fator), round(img.height * fator)), Image.LANCZOS)
    alvo = Path(caminho).with_name(Path(caminho).stem + "_perfil.png")
    img.save(alvo, "PNG")
    return alvo


def miniatura_logo(caminho, lado=360):
    """PNG pequeno em base64 para a tela mostrar a logo que o sistema achou."""
    from PIL import Image
    img = Image.open(caminho).convert("RGBA")
    img.thumbnail((lado, lado))
    saida = io.BytesIO()
    img.save(saida, "PNG", optimize=True)
    return base64.b64encode(saida.getvalue()).decode()


def logo_do_instagram(site):
    """Foto de perfil do Instagram: na maioria dos clientes é a própria logo."""
    import requests
    achado = re.search(r"instagram\.com/([A-Za-z0-9._]+)", site or "")
    if not achado or achado.group(1).lower() in {"p", "reel", "explore", "stories"}:
        return ""
    usuario = achado.group(1)
    try:
        r = requests.get(f"https://i.instagram.com/api/v1/users/web_profile_info/?username={usuario}",
                         headers={"User-Agent": "Instagram 219.0.0.12.117 Android", "x-ig-app-id": "936619743392459"},
                         timeout=20)
        if r.status_code == 200:
            usuario_dados = (r.json().get("data") or {}).get("user") or {}
            url = usuario_dados.get("profile_pic_url_hd") or usuario_dados.get("profile_pic_url")
            if url:
                return url
    except Exception:
        pass
    for ua in ("facebookexternalhit/1.1", "Mozilla/5.0 (compatible; Googlebot/2.1)"):
        try:
            r = requests.get(f"https://www.instagram.com/{usuario}/", headers={"User-Agent": ua}, timeout=20)
            m = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
            if m:
                return m.group(1).replace("&amp;", "&")
        except Exception:
            pass
    try:
        r = requests.get(f"https://unavatar.io/instagram/{usuario}?fallback=false", timeout=30)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
            return r.url
    except Exception:
        pass
    return ""


def _logo_da_home(site):
    if re.search(r"instagram\.com/", site or ""):
        achada = logo_do_instagram(site)
        if achada:
            evento("extracao", "logo = foto de perfil do Instagram")
        return achada
    import extracao
    try:
        final, soup, _ = extracao._soup(selecao.normalizar_site(site))
    except Exception:
        return ""
    organizacao = extracao._first_jsonld(soup, "Organization")
    achada = extracao._logo(soup, final, organizacao)
    if achada:
        return achada
    return _logo_pelo_arquivo(soup, final)


def _home_fala_dos_produtos(base, nomes_produtos):
    """A home achada só vale se citar ao menos 2 palavras dos nomes dos produtos do catálogo."""
    import extracao
    try:
        _, soup, _ = extracao._soup(base)
    except Exception:
        return False
    texto = _sem_acento(soup.get_text(" ", strip=True))[:200000]
    chaves = set()
    for nome in nomes_produtos:
        chaves.update(selecao.palavras_chave(nome))
    return sum(1 for c in chaves if len(c) >= 4 and c in texto) >= 2


def logo_pela_web(cliente, site_informado="", nomes_produtos=()):
    """(site, url da logo) buscando o site oficial pelo nome do cliente.
    Só aceita domínio que contenha o nome do cliente, para não pegar logo de outra empresa."""
    from urllib.parse import urlparse
    nome = _sem_acento(cliente or "")
    palavras = [p for p in re.findall(r"[a-z0-9]{3,}", nome)
                if p not in {"ltda", "distribuidora", "comercio", "industria", "teste", "anexo", "loja"}]
    if not palavras:
        return "", ""
    informado = (urlparse(selecao.normalizar_site(site_informado)).hostname or "") if site_informado else ""
    vistos = set()
    for consulta in (f"{cliente} site oficial",):
        for url in selecao.buscar_duckduckgo(consulta, 8) or selecao.buscar_bing(consulta, 8):
            host = (urlparse(url).hostname or "").lower()
            if not host or host == informado or selecao.MERCADO_LIVRE.search(host):
                continue
            if not all(p in host.replace("-", "") for p in palavras[:2]):
                continue
            base = f"https://{host}/"
            if base in vistos:
                continue
            vistos.add(base)
            if nomes_produtos and not _home_fala_dos_produtos(base, nomes_produtos):
                continue
            achada = _logo_da_home(base)
            if achada:
                return base, achada
    return "", ""


def _logo_pelo_arquivo(soup, base):
    """Recurso extra: logo sem alt/classe, reconhecida so pelo nome do arquivo (ex.: jh-logo-2019-transp.webp).

    Ignora imagens de carrossel/slider e de outras marcas em cache de slider."""
    from urllib.parse import urljoin
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        arquivo = src.rsplit("/", 1)[-1].lower()
        if "logo" not in arquivo or any(x in src.lower() for x in ("slider", "carousel", "banner", "/cache/")):
            continue
        return urljoin(base, src)
    return ""


CORES_LOGO = ((17, 58, 110), (122, 31, 61), (22, 92, 70), (92, 45, 145), (150, 70, 20), (30, 30, 30))


def logo_tipografica(cliente, pasta):
    """Pedido sem logo (sem site ou site sem logo): logo de texto com o nome do cliente,
    para os banners terem marca e paleta. Cor fixa pelo nome, sempre a mesma."""
    import hashlib
    from PIL import Image, ImageDraw, ImageFont
    nome = " ".join(str(cliente or "Cliente").split()) or "Cliente"
    cor = CORES_LOGO[int(hashlib.sha256(nome.lower().encode()).hexdigest(), 16) % len(CORES_LOGO)]
    fonte = None
    for arquivo in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "LiberationSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            fonte = ImageFont.truetype(arquivo, 120)
            break
        except OSError:
            continue
    if fonte is None:
        try:
            fonte = ImageFont.load_default(size=120)
        except TypeError:
            fonte = ImageFont.load_default()
    rascunho = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    palavras = nome.upper().split()

    def medir(texto):
        caixa = rascunho.textbbox((0, 0), texto, font=fonte)
        return caixa[2] - caixa[0], caixa[3] - caixa[1], caixa

    def dividir(qtd):
        if qtd <= 1 or len(palavras) < qtd:
            return [" ".join(palavras)]
        melhor = None
        import itertools
        for cortes in itertools.combinations(range(1, len(palavras)), qtd - 1):
            limites = (0,) + cortes + (len(palavras),)
            linhas = [" ".join(palavras[a:b]) for a, b in zip(limites, limites[1:])]
            maior = max(medir(linha)[0] for linha in linhas)
            if melhor is None or maior < melhor[0]:
                melhor = (maior, linhas)
        return melhor[1]

    altura_linha = medir("AGJ")[1]
    entrelinha = int(altura_linha * 0.35)
    margem = 40
    linhas = [" ".join(palavras)]
    for qtd in range(1, min(len(palavras), 4) + 1):
        linhas = dividir(qtd)
        largura = max(medir(linha)[0] for linha in linhas) + 2 * margem
        altura = len(linhas) * altura_linha + (len(linhas) - 1) * entrelinha + 2 * margem + 24
        if largura / altura <= 4:
            break
    largura = max(medir(linha)[0] for linha in linhas)
    altura_total = len(linhas) * altura_linha + (len(linhas) - 1) * entrelinha
    img = Image.new("RGBA", (largura + 2 * margem, altura_total + 2 * margem + 24), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(img)
    topo = margem
    for linha in linhas:
        _, _, caixa = medir(linha)
        desenho.text((margem - caixa[0], topo - rascunho.textbbox((0, 0), "AGJ", font=fonte)[1]),
                     linha, font=fonte, fill=cor + (255,))
        topo += altura_linha + entrelinha
    if img.width / img.height > 5.5:
        nova_altura = int(img.width / 5.5)
        maior = Image.new("RGBA", (img.width, nova_altura), (0, 0, 0, 0))
        maior.paste(img, (0, (nova_altura - img.height) // 2))
        img = maior
    desenho = ImageDraw.Draw(img)
    desenho.rectangle((margem, img.height - margem + 4, margem + max(largura // 4, 60), img.height - margem + 16),
                      fill=cor + (255,))
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / "logo_texto.png"
    img.save(alvo, "PNG")
    return alvo


def montar_catalogo(entrada):
    """Coleta, filtra, seleciona por IA e monta. Levanta PrecisaCatalogo."""
    cliente, site = entrada["cliente"], str(entrada.get("site") or "").strip()
    segmento_informado = str(entrada.get("segmento") or "").strip()
    foco = str(entrada.get("foco") or "").strip()
    if foco:
        evento("extracao", f"foco do pedido: {foco}")
    validos, descartes, fonte_anexo = [], [], None
    tipos_da_empresa = []
    if site and re.search(r"instagram\.com/|facebook\.com/|linktr\.ee/", site):
        evento("extracao", f"{site} é rede social: pesquisando no Google o site oficial e o que {cliente} vende")
        descoberta = selecao.descobrir_empresa(cliente, site)
        tipos_da_empresa = descoberta.get("tipos") or []
        if descoberta.get("site_oficial"):
            evento("extracao", f"site oficial achado no Google: {descoberta['site_oficial']}")
            site = descoberta["site_oficial"]
        else:
            evento("extracao", "o Google não mostrou site oficial; buscando os produtos pela web")
            site = ""
        if tipos_da_empresa:
            evento("extracao", "produtos que a empresa vende, segundo o Google: " + ", ".join(tipos_da_empresa))
        if not segmento_informado and descoberta.get("segmento"):
            segmento_informado = descoberta["segmento"]
    coleta = {"site": selecao.normalizar_site(site) if site else "", "plataforma": "nenhuma"}
    if entrada.get("anexo"):
        import anexo
        evento("extracao", f"lendo o anexo {entrada['anexo']['nome']}")
        fonte_anexo, do_anexo, descartes_anexo = anexo.candidatos_do_anexo(
            entrada["anexo"]["nome"], entrada["anexo"]["conteudo_base64"])
        validos, descartes_filtro = selecao.filtrar_candidatos(do_anexo)
        descartes += descartes_anexo + descartes_filtro
        coleta["plataforma"] = fonte_anexo
        evento("extracao", f"anexo: {len(validos)} produtos válidos")
    if site and len(validos) < selecao.MAXIMO_PRODUTOS:
        evento("extracao", f"lendo {site}")
        try:
            coleta_site, candidatos = selecao.coletar_candidatos(site, foco)
            if not fonte_anexo:
                coleta = coleta_site
        except Exception as erro:
            candidatos = []
            evento("extracao", f"coleta no site falhou: {type(erro).__name__}: {erro}", "aviso")
        do_site, descartes_site = selecao.filtrar_candidatos(candidatos)
        vistos = {selecao.sem_acento(v["nome"]) for v in validos}
        validos += [v for v in do_site if selecao.sem_acento(v["nome"]) not in vistos]
        descartes += descartes_site
        evento("extracao", f"{len(do_site)} candidatos válidos no site, {len(descartes_site)} descartados")
    if site and len(validos) < selecao.MAXIMO_PRODUTOS:
        secoes, descartes_secoes = selecao.filtrar_candidatos(
            selecao.coletar_secoes(selecao.normalizar_site(site)))
        vistos = {v["imagem"] for v in validos} | {selecao.sem_acento(v["nome"]) for v in validos}
        novos = [c for c in secoes if c["imagem"] not in vistos and selecao.sem_acento(c["nome"]) not in vistos]
        if novos:
            evento("extracao", f"páginas de seção do site: +{len(novos)} candidatos válidos")
            validos += novos
            descartes += descartes_secoes
            if coleta.get("plataforma") in (None, "nenhuma"):
                coleta["plataforma"] = "secoes"
    custo = {"modelo": (selecao.MODELO_SELECAO if os.environ.get("GEMINI_API_KEY")
                        else selecao.MODELO_OPENROUTER), "custo_usd": 0.0, "tokens_entrada": 0,
             "tokens_saida": 0, "com_imagens": False}
    if site and len(validos) < selecao.MAXIMO_PRODUTOS:
        fotos = selecao.coletar_fotos_sem_nome(selecao.normalizar_site(site))
        vistos = {v["imagem"] for v in validos}
        fotos = [f for f in fotos if f["imagem"] not in vistos]
        if fotos:
            evento("extracao", f"lendo o nome do produto em {len(fotos)} fotos sem nome do site")
            nomeados, descartes_fotos, custo_fotos = selecao.nomear_pela_imagem(fotos, cliente)
            for k in ("custo_usd", "tokens_entrada", "tokens_saida"):
                custo[k] += custo_fotos.get(k) or 0
            aprovados, descartes_nomeados = selecao.filtrar_candidatos(nomeados)
            validos += aprovados
            descartes += descartes_fotos + descartes_nomeados
    if len(validos) < selecao.MINIMO_PRODUTOS and not tipos_da_empresa and not fonte_anexo:
        tipos_da_empresa = selecao.descobrir_empresa(cliente, site).get("tipos") or []
        if tipos_da_empresa:
            evento("extracao", "produtos que a empresa vende, segundo o Google: " + ", ".join(tipos_da_empresa))
    if len(validos) < selecao.MINIMO_PRODUTOS or foco:
        evento("extracao", f"site com só {len(validos)} produtos: buscando na web produtos do mesmo tipo")
        categorias_site = []
        for v in validos:
            if v.get("categoria") and v["categoria"] not in categorias_site:
                categorias_site.append(v["categoria"])
        for secao in (selecao.coletar_titulos_de_linha(selecao.normalizar_site(site)) if site else []):
            if secao not in categorias_site:
                categorias_site.append(secao)
        nomes_conhecidos = [v["nome"] for v in validos if v.get("nome_lido_na_imagem")] + [v["nome"] for v in validos]
        brutos = selecao.buscar_candidatos_web(cliente, segmento_informado, categorias_site,
                                               site or "https://sem-site.invalid/", nomes_conhecidos,
                                               foco=foco, tipos=tipos_da_empresa)
        if len(brutos) < selecao.MINIMO_PRODUTOS:
            brutos += selecao.buscar_candidatos(cliente, segmento_informado)
        achados, descartes_busca = selecao.filtrar_candidatos(brutos)
        vistos = {v["imagem"] for v in validos} | {selecao.sem_acento(v["nome"]) for v in validos}
        validos += [a for a in achados if a["imagem"] not in vistos
                    and selecao.sem_acento(a["nome"]) not in vistos]
        descartes += descartes_busca
    if foco:
        da_busca = [v for v in validos if v["origem"] == "busca"]
        validos = da_busca[:24] + [v for v in validos if v["origem"] != "busca"]
    validos = validos[:selecao.MAXIMO_CANDIDATOS]
    if validos:
        evento("extracao", "IA (fila gratuita) conferindo se cada foto mostra o produto do nome")
        validos, descartes_fotos, custo_fotos = selecao.conferir_fotos(validos, cliente)
        for k in ("custo_usd", "tokens_entrada", "tokens_saida"):
            custo[k] += custo_fotos.get(k) or 0
        descartes += descartes_fotos
        unicos, nomes = [], set()
        for v in validos:
            chave = selecao.sem_acento(v["nome"])
            if chave in nomes:
                descartes.append({"nome": v["nome"], "motivo": "duplicado (mesmo produto em outra loja)"})
                continue
            nomes.add(chave)
            unicos.append(v)
        validos = unicos
    if len(validos) < selecao.MINIMO_PRODUTOS:
        raise selecao.PrecisaCatalogo(
            f"só {len(validos)} produtos com URL de origem e imagem válida "
            f"{'no anexo, ' if fonte_anexo else ''}no site e na busca "
            f"(mínimo {selecao.MINIMO_PRODUTOS}); "
            + ("o anexo precisa ter nome e foto de cada produto; mande outro PDF ou planilha"
               if fonte_anexo else "mande o catálogo em PDF ou planilha"),
            {"custo": custo, "descartes": descartes})
    evento("extracao", f"IA (fila gratuita) escolhendo entre {len(validos)} candidatos")
    escolha, custo_selecao = selecao.selecionar(validos, cliente, site or f"anexo {fonte_anexo}",
                                                segmento_informado, foco)
    for k in ("custo_usd", "tokens_entrada", "tokens_saida"):
        custo_selecao[k] = (custo_selecao.get(k) or 0) + (custo.get(k) or 0)
    custo = custo_selecao
    evento("extracao", f"seleção: {len(escolha.get('selecionados') or [])} produtos, "
                       f"custo US$ {custo['custo_usd']:.4f}")
    segmento_modelo = str(escolha.get("segmento") or "").strip()
    try:
        catalogo, precos, situacao, similares, regra_preco, descartes_modelo = selecao.montar_pela_selecao(
            coleta, validos, escolha, cliente, segmento_informado or segmento_modelo,
            entrada.get("descricao"))
        fora = next((x["_fora_do_foco"] for x in descartes_modelo if "_fora_do_foco" in x), 0)
        descartes_modelo = [x for x in descartes_modelo if "_fora_do_foco" not in x]
        if foco and fora:
            evento("extracao", f"{fora} de {len(precos)} produtos NÃO são do foco pedido "
                               f"({foco}): o site e a busca não tinham o suficiente", "aviso")
            entrada["_aviso_foco"] = (f"{fora} de {len(precos)} produtos NÃO são do foco pedido ({foco}); "
                                      "o site e a busca não trouxeram produtos suficientes desse tipo")
    except selecao.PrecisaCatalogo as erro:
        extra = erro.args[1] if len(erro.args) > 1 else {}
        raise selecao.PrecisaCatalogo(erro.args[0], {"custo": custo, "descartes": descartes
                                                     + extra.get("descartes_modelo", [])})
    descartes += descartes_modelo
    return {"catalogo": catalogo, "precos": precos, "preco": situacao, "similares": similares,
            "regra_preco": regra_preco, "candidatos": validos,
            "custo": custo, "descartes": descartes, "segmento_modelo": segmento_modelo,
            "candidatos_validos": len(validos),
            "nomes_lidos_na_imagem": sum(1 for p in precos if p.get("nome_lido_na_imagem")),
            "fonte": (("pdf" if fonte_anexo == "pdf" else "planilha") if any(p["fonte"] == "anexo" for p in precos)
                      else "busca" if any(p["fonte"] == "busca" for p in precos) else "site")}


def extrair(entrada):
    import atendimento
    pedido_id = entrada["pedido_id"]
    observacoes = []
    try:
        montado = montar_catalogo(entrada)
    except selecao.SemCreditoOpenRouter as erro:
        return {"sem_credito": str(erro)}
    except selecao.PrecisaCatalogo as erro:
        extra = erro.args[1] if len(erro.args) > 1 else {}
        return {"precisa_catalogo": erro.args[0], "custo": extra.get("custo"),
                "descartes": (extra.get("descartes") or [])[:80]}
    catalogo, precos = montado["catalogo"], montado["precos"]

    segmento, origem, criterio = entrada.get("segmento"), "informado", None
    if not str(segmento or "").strip():
        segmento, criterio = segmento_do_modelo(montado["segmento_modelo"])
        if not segmento:
            texto = " ".join(p["nome"] for p in precos)
            segmento, criterio = inferir_segmento(texto)
        origem = "inferido"
        evento("extracao", f"segmento inferido: {segmento} ({criterio})")
    catalogo["setor"] = segmento

    caminho = gravar_catalogo(catalogo, pedido_id)
    valido, saida_validacao = atendimento.validar(caminho)
    if not valido:
        raise RuntimeError("catálogo reprovado no validar_poc.py: " + saida_validacao[-1500:])
    evento("extracao", "validar_poc.py: 0 erros")

    estimados = sum(1 for p in precos if p["origem"] == "estimado")
    if estimados:
        observacoes.append(f"{estimados} de {len(precos)} preços são ESTIMADOS (sem preço na página); "
                           f"{montado['regra_preco']}")
    if montado.get("nomes_lidos_na_imagem"):
        observacoes.append(f"{montado['nomes_lidos_na_imagem']} nomes de produto foram LIDOS NA FOTO do site "
                           "(o site não tinha o nome em texto); confira na curadoria")
    if entrada.get("_aviso_foco"):
        observacoes.append(entrada["_aviso_foco"])
    if montado["similares"]:
        observacoes.append("há produtos SIMILARES achados na busca que NÃO são da marca do cliente")
        evento("extracao", "produtos similares de outras marcas no catálogo", "aviso")

    logo_url = _logo_da_home(entrada["site"]) if entrada.get("site") else None
    if logo_url:
        original = selecao._imagem_cheia(logo_url)
        if original != logo_url:
            evento("extracao", "logo do Wix: usando o arquivo original (a versão da página vem em AVIF)")
            logo_url = original
    logo = atendimento.baixar_logo(logo_url, atendimento.prefixo(caminho.name)) if logo_url else None
    bruta = logo
    logo, aviso_logo = conferir_logo(logo)
    logo_origem = "site" if logo else None
    if not logo and bruta and re.search(r"instagram\.com/", entrada.get("site") or ""):
        logo = str(foto_de_perfil_como_logo(bruta))
        logo_origem, aviso_logo = "instagram", None
        evento("extracao", "logo = foto de perfil do Instagram, usada mesmo pequena (não passou na régua)")
    if not logo:
        site_achado, logo_web = logo_pela_web(entrada.get("cliente"), entrada.get("site"),
                                                  [p["nome"] for p in precos])
        if logo_web:
            baixada = atendimento.baixar_logo(logo_web, atendimento.prefixo(caminho.name))
            baixada, aviso_web = conferir_logo(baixada)
            if aviso_web:
                observacoes.append(aviso_web)
            if baixada:
                logo, logo_url, logo_origem = baixada, logo_web, "web"
                observacoes.append(f"logo achada na web, no site {site_achado}; confira se é a do cliente")
                evento("extracao", f"logo achada na web em {site_achado}")
    if aviso_logo:
        observacoes.append(aviso_logo)
        evento("extracao", aviso_logo, "aviso")
    if not logo:
        logo_url = None
        try:
            logo = str(logo_tipografica(entrada.get("cliente"), pasta_pedido(pedido_id)))
            logo_origem = "texto"
            observacoes.append(("nenhuma logo identificável foi encontrada no site" if entrada.get("site")
                                else "pedido sem site") + ": a logo dos banners foi GERADA a partir do nome do "
                               "cliente (texto); troque pela logo real se o cliente mandar")
            evento("extracao", "sem logo: banners com logo de texto gerada pelo nome do cliente", "aviso")
        except Exception as erro:
            logo = None
            observacoes.append(f"sem logo e a logo de texto falhou ({type(erro).__name__}: {erro}); "
                               "portal sai sem banner de identidade")
            evento("extracao", "sem logo: portal sai sem banner", "aviso")

    categorias = next(e for e in catalogo["etapas"] if e.get("endpoint") == "categories")["requests"]
    resumo = {"produtos": len(precos), "categorias": len(categorias), "fonte": montado["fonte"],
              "preco": montado["preco"], "precos": precos,
              "produtos_similares": montado["similares"], "executivo": entrada.get("executivo"),
              "segmento": segmento, "segmento_origem": origem, "segmento_criterio": criterio,
              "regra_preco_estimado": montado["regra_preco"],
              "modelo": montado["custo"]["modelo"], "custo_usd": montado["custo"]["custo_usd"],
              "tokens": montado["custo"]["tokens_entrada"] + montado["custo"]["tokens_saida"],
              "candidatos_validos": montado["candidatos_validos"],
              "nomes_lidos_na_imagem": montado.get("nomes_lidos_na_imagem", 0),
              "descartes": montado["descartes"][:80],
              "observacoes": " · ".join(observacoes)}
    saida = {"catalogo": catalogo, "resumo": resumo, "logo_url": logo_url,
             "segmento": segmento, "segmento_origem": origem, "custo": montado["custo"]}
    if logo:
        saida["logo"] = {"nome": Path(logo).name,
                         "conteudo_base64": base64.b64encode(Path(logo).read_bytes()).decode()}
        saida["logo_previa"] = miniatura_logo(logo)
        saida["logo_clara"] = logo_clara(logo)
    saida["logo_origem"] = logo_origem
    avisos_logo = [o for o in observacoes if "logo" in o]
    saida["logo_aviso"] = " · ".join(avisos_logo)[:800] or None
    return saida


def trocar_logo(entrada):
    """Logo enviada pelo usuário: valida na régua, gera a miniatura e, com o
    portal já criado, sobe logo e favicon pelo subir_identidade (confere o byte
    servido por GET). Os banners são refeitos depois pela ação previa."""
    pedido_id = entrada["pedido_id"]
    pasta = pasta_pedido(pedido_id) / "logo_enviada"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = re.sub(r"[^a-zA-Z0-9._-]", "_", entrada["logo"]["nome"]) or "logo.png"
    alvo = pasta / nome
    alvo.write_bytes(base64.b64decode(entrada["logo"]["conteudo_base64"]))
    usada, aviso = conferir_logo(str(alvo))
    if not usada:
        return {"recusada": aviso}
    saida = {"logo": {"nome": Path(usada).name,
                      "conteudo_base64": base64.b64encode(Path(usada).read_bytes()).decode()},
             "logo_previa": miniatura_logo(usada), "logo_clara": logo_clara(usada)}
    if entrada.get("portal_id"):
        import subir_identidade
        evento("logo", "subindo a logo nova no portal e conferindo por GET")
        codigo = subir_identidade.main(["--org", ORG, "--portal", entrada["portal_id"], "--logo", str(usada),
                                        "--nome", entrada.get("cliente") or "", "--gravar"])
        saida["portal_logo"] = "conferida" if codigo == 0 else f"falhou (código {codigo})"
    return saida


GABARITO = (
    ("JH", "https://distribuidorajh.com.br/", "Arquivos Json/distribuidora_jh_poc.json", "coleta_jh.json"),
    ("Master Foods Mix", "https://www.masterfoodsmix.com.br/", "Arquivos Json/master_foods_mix_poc.json",
     "coleta_masterfoodsmix.json"),
    ("MTO", "https://loja-bio-infinity.lojaintegrada.com.br/", "Arquivos Json/mto_distribuidora_poc.json",
     "coleta_mto.json"),
    ("Lise", "https://fise.com.br/", "Arquivos Json/lise_poc.json", "coleta_lise.json"),
    ("Fise", "https://fise.com.br/", None, "coleta_fise.json"),
    ("Minas Couros", "https://minascourosvonixx.catalogo.com.br/", "Arquivos Json/minas_couros_poc.json",
     "coleta_minascouros.json"),
)


def _produtos_do_json(catalogo):
    etapa = next((e for e in catalogo.get("etapas") or [] if e.get("endpoint") == "products"), None)
    return [{"nome": r["payload"].get("name"), "imagem": r.get("temp_image_url") or ""}
            for r in (etapa or {}).get("requests") or []]


def _chave_imagem(url):
    arquivo = str(url or "").split("?")[0].rsplit("/", 1)[-1].lower()
    return re.sub(r"(-\d+x\d+|-scaled|-e\d+)(?=\.)", "", arquivo)


def _motivos(novos, entregues, montado, coleta_antiga):
    """Uma linha por produto que nao bateu, nos dois sentidos."""
    def chaves(p):
        return {_sem_acento(p["nome"]), _chave_imagem(p["imagem"])}
    antigos = [{"nome": i.get("nome") or "", "imagem": i.get("imagem") or ""}
               for i in coleta_antiga.get("itens") or []]
    chaves_antigas = set().union(*[chaves(p) for p in antigos]) if antigos else set()
    chaves_entregues = set().union(*[chaves(p) for p in entregues]) if entregues else set()
    chaves_novas = set().union(*[chaves(p) for p in novos]) if novos else set()
    candidatos = montado.get("candidatos") or []
    chaves_candidatos = set().union(*[chaves(p) for p in candidatos]) if candidatos else set()
    descartes = {_sem_acento(d["nome"]): d["motivo"] for d in montado.get("descartes") or []}
    linhas = []
    for p in novos:
        if chaves(p) & chaves_entregues:
            continue
        if chaves(p) & chaves_antigas:
            motivo = "estava na coleta antiga, mas a POC entregue escolheu outros"
        else:
            motivo = "não estava na coleta antiga (o site mudou ou a coleta nova achou mais)"
        linhas.append(f"+ {p['nome']}: {motivo}")
    for p in entregues:
        if chaves(p) & chaves_novas:
            continue
        chave = _sem_acento(p["nome"])
        if chave in descartes:
            motivo = f"descartado agora: {descartes[chave]}"
        elif chaves(p) & chaves_candidatos:
            motivo = next((d["motivo"] for d in montado.get("descartes") or []
                           if _sem_acento(d["nome"]) == chave or
                           any(_chave_imagem(c["imagem"]) == _chave_imagem(p["imagem"])
                               and _sem_acento(c["nome"]) == _sem_acento(d["nome"]) for c in candidatos)),
                          "coletado e válido, mas o modelo não escolheu")
        else:
            motivo = "não apareceu na coleta de hoje (nome/imagem diferentes ou saiu do site)"
        linhas.append(f"- {p['nome']}: {motivo}")
    return linhas


def avaliar(entrada):
    """Roda a extracao nova nos clientes do gabarito e compara com o entregue."""
    import time
    import verificar_imagens
    linhas = []
    for cliente, site, arquivo, arquivo_coleta in GABARITO:
        if entrada.get("clientes") and cliente not in entrada["clientes"]:
            continue
        evento("avaliacao", f"{cliente}: {site}")
        linha = {"cliente": cliente, "site": site}
        entregues = []
        if arquivo and (REPO / arquivo).exists():
            entregues = _produtos_do_json(json.loads((REPO / arquivo).read_text(encoding="utf-8")))
        coleta_antiga = {}
        if (REPO / arquivo_coleta).exists():
            coleta_antiga = json.loads((REPO / arquivo_coleta).read_text(encoding="utf-8"))
        linha["gabarito"] = len(entregues) if arquivo else None
        inicio = time.monotonic()
        try:
            montado = montar_catalogo({"cliente": cliente, "site": site})
        except selecao.SemCreditoOpenRouter as erro:
            linha.update(status="sem_credito", motivo=str(erro), produtos=0,
                         segundos=round(time.monotonic() - inicio))
            linhas.append(linha)
            continue
        except selecao.PrecisaCatalogo as erro:
            extra = erro.args[1] if len(erro.args) > 1 else {}
            linha["descartes"] = [f"{x['nome']}: {x['motivo']}" for x in extra.get("descartes") or []][:60]
            linha.update(status="precisa_catalogo", motivo=erro.args[0], produtos=0,
                         segundos=round(time.monotonic() - inicio),
                         custo_usd=(extra.get("custo") or {}).get("custo_usd"))
            linhas.append(linha)
            continue
        except Exception as erro:
            linha.update(status="falhou", motivo=f"{type(erro).__name__}: {erro}"[:300], produtos=0,
                         segundos=round(time.monotonic() - inicio))
            linhas.append(linha)
            continue
        segundos = round(time.monotonic() - inicio)
        novos = _produtos_do_json(montado["catalogo"])
        nomes = {_sem_acento(p["nome"]) for p in entregues}
        imagens = {_chave_imagem(p["imagem"]) for p in entregues}
        batem = sum(1 for p in novos if _sem_acento(p["nome"]) in nomes
                    or _chave_imagem(p["imagem"]) in imagens)
        laudos = [verificar_imagens.conferir((p["nome"], p["imagem"])) for p in novos]
        lixo = [p["nome"] for p in novos if selecao.NAO_E_PRODUTO.search(_sem_acento(p["nome"]))
                or selecao.IMAGEM_NAO_E_PRODUTO.search(p["imagem"])]
        linha.update(status="ok", segundos=segundos, produtos=len(novos), batem=batem,
                     imagens_validas=sum(1 for laudo in laudos if laudo[2]), lixo=lixo,
                     preco=montado["preco"], regra_preco=montado["regra_preco"],
                     similares=montado["similares"], fonte=montado["fonte"],
                     modelo=montado["custo"]["modelo"], custo_usd=montado["custo"]["custo_usd"],
                     com_imagens=montado["custo"]["com_imagens"],
                     candidatos_validos=montado["candidatos_validos"],
                     nao_bateram=_motivos(novos, entregues, montado, coleta_antiga),
                     descartados_modelo=[f"{d['nome']}: {d['motivo'][8:]}" for d in montado["descartes"]
                                         if d["motivo"].startswith("modelo")][:60],
                     precos=[f"{p['nome']}: R$ {p['preco']:.2f} ({p['origem']}; {p['regra']})"
                             for p in montado["precos"]])
        linhas.append(linha)
    return {"linhas": linhas}


COR_LOGO_CLARA = "#1C1C1E"


EMBRULHO_PALETA = r"""
import json, sys
from pathlib import Path
gerador = Path(sys.argv[1]); paleta = json.loads(sys.argv[2])
sys.path.insert(0, str(gerador.parent))
sys.argv = [str(gerador)] + sys.argv[3:]
import gerar_banners
original = gerar_banners.mod_paleta.extrair
def extrair(logo, cor_informada=None):
    base = original(logo, cor_informada)
    base.update(paleta)
    return base
gerar_banners.mod_paleta.extrair = extrair
sys.exit(gerar_banners.main(sys.argv[1:]))
"""


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _rgb(texto):
    texto = texto.lstrip("#")
    return tuple(int(texto[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb):
    def canal(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _misturar(rgb, alvo, peso):
    return tuple(c + (t - c) * peso for c, t in zip(rgb, alvo))


def _legivel_sobre(cor, fundo, minimo=3.0):
    cor = tuple(cor)
    escurecer = _lum(fundo) > 0.4
    for _ in range(20):
        if _contraste(cor, fundo) >= minimo:
            break
        cor = _misturar(cor, (0, 0, 0) if escurecer else (255, 255, 255), 0.15)
    return cor


def variacao_de_paleta(marca_hex, feedback_texto, anterior_hex=None):
    """Escolhe uma paleta NOVA a cada refazer. Lê o pedido do executivo
    (claro/branco, escuro, sem verde) e nunca devolve o mesmo fundo de antes."""
    import random
    import unicodedata
    marca = _rgb(marca_hex)
    texto = unicodedata.normalize("NFKD", (feedback_texto or "").lower()).encode("ascii", "ignore").decode()
    quer_claro = any(p in texto for p in ("clar", "branc", "leve", "suave", "pastel", "light"))
    quer_escuro = any(p in texto for p in ("escur", "preto", "dark"))
    claros = [("fundo claro neutro", (247, 248, 250)), ("fundo branco", (255, 255, 255)),
              ("fundo claro na cor da marca", _misturar(marca, (255, 255, 255), 0.88)),
              ("fundo creme", (250, 247, 240)), ("fundo cinza claro", (236, 238, 241))]
    escuros = [("fundo grafite", (28, 28, 30)), ("fundo marca escura", _misturar(marca, (0, 0, 0), 0.55))]
    marca_pura = [("fundo na cor da marca", marca)]
    if quer_claro:
        opcoes = claros
    elif quer_escuro:
        opcoes = escuros
    else:
        opcoes = claros + escuros + marca_pura
    anterior = anterior_hex.upper() if anterior_hex else None
    opcoes = [o for o in opcoes if _hex(o[1]) != anterior] or opcoes
    nome, fundo = random.choice(opcoes)
    if _lum(fundo) > 0.4:
        destaque = _legivel_sobre(marca, fundo)
        neutra = (16, 20, 24)
    else:
        destaque = marca if _contraste(marca, fundo) >= 3 else _legivel_sobre(_misturar(marca, (255, 255, 255), 0.4), fundo)
        neutra = (247, 248, 250)
    return nome, {"principal": _hex(fundo), "destaque": _hex(destaque), "neutra": _hex(neutra)}


PALAVRAS_CLARO = ("clar", "branc", "leve", "suave", "pastel", "light", "limp")
PALAVRAS_ESCURO = ("escur", "preto", "dark", "noturn")


def _texto_simples(texto):
    return unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode()


def gosto_do_executivo(preferencias):
    """'claro', 'escuro' ou '' pelos pedidos de mudança que o executivo já fez (recentes pesam mais)."""
    placar = 0.0
    for i, texto in enumerate(preferencias or []):
        t = _texto_simples(texto)
        peso = 1.0 / (1 + i * 0.3)
        if any(p in t for p in PALAVRAS_CLARO):
            placar += peso
        if any(p in t for p in PALAVRAS_ESCURO):
            placar -= peso
    return "claro" if placar >= 0.9 else "escuro" if placar <= -0.9 else ""


def _saturacao(rgb):
    alto, baixo = max(rgb), min(rgb)
    return 0 if alto == 0 else (alto - baixo) / alto


def _matiz(rgb):
    import colorsys
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[0] * 360


def _dist_matiz(a, b):
    d = abs(_matiz(a) - _matiz(b)) % 360
    return min(d, 360 - d)


def cores_da_logo(logo):
    """Cores de marca da logo (saturadas, sem branco/preto), da mais presente para a menos."""
    from PIL import Image
    try:
        img = Image.open(logo).convert("RGBA")
    except Exception:
        return []
    img.thumbnail((160, 160))
    contagem = {}
    for r, g, b, a in img.getdata():
        if a < 200 or _saturacao((r, g, b)) < 0.4 or max(r, g, b) < 60:
            continue
        chave = (r // 24 * 24 + 12, g // 24 * 24 + 12, b // 24 * 24 + 12)
        contagem[chave] = contagem.get(chave, 0) + 1
    total = sum(contagem.values()) or 1
    return [c for c, n in sorted(contagem.items(), key=lambda kv: -kv[1]) if n / total > 0.03][:4]


def cores_do_site(site):
    """Cores de identidade do site: theme-color, variáveis CSS e cores mais usadas nos estilos."""
    import requests
    from urllib.parse import urljoin
    if not site or re.search(r"instagram\.com|facebook\.com|linktr\.ee", site):
        return []
    cab = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
    try:
        base = selecao.normalizar_site(site)
        pagina = requests.get(base, headers=cab, timeout=15).text
    except Exception:
        return []
    textos = [pagina]
    for href in re.findall(r'<link[^>]+rel="?stylesheet"?[^>]+href="([^"]+)"', pagina)[:4]:
        try:
            textos.append(requests.get(urljoin(base, href), headers=cab, timeout=10).text[:400000])
        except Exception:
            pass
    contagem = {}
    for m in re.findall(r'name="theme-color"\s+content="(#[0-9a-fA-F]{6})"', pagina):
        contagem[m.upper()] = contagem.get(m.upper(), 0) + 40
    for texto in textos:
        for m in re.findall(r"#([0-9a-fA-F]{6})\b", texto):
            contagem["#" + m.upper()] = contagem.get("#" + m.upper(), 0) + 1
    saida = []
    for hexa, _ in sorted(contagem.items(), key=lambda kv: -kv[1]):
        rgb = _rgb(hexa)
        if _saturacao(rgb) < 0.4 or max(rgb) < 60:
            continue
        if all(_dist_matiz(rgb, o) > 20 for o in saida):
            saida.append(rgb)
        if len(saida) >= 4:
            break
    return saida


def identidade_visual(site, logo):
    """(marca, apoio, origem): a cor da marca vem da logo e é confirmada/ajustada pelo site;
    a cor de apoio é a segunda cor do site (ou da logo), nunca um matiz inventado."""
    da_logo = cores_da_logo(logo) if logo else []
    do_site = cores_do_site(site)
    marca, apoio, origem = None, None, []
    if da_logo:
        marca = da_logo[0]
        origem.append("logo")
        parecida = next((c for c in do_site if _dist_matiz(c, marca) <= 18), None)
        if parecida:
            marca = parecida
            origem.append("site")
    elif do_site:
        marca = do_site[0]
        origem.append("site")
    candidatas = [c for c in do_site + da_logo if marca is None or _dist_matiz(c, marca) > 40]
    apoio = candidatas[0] if candidatas else None
    return (_hex(marca) if marca else None, _hex(apoio) if apoio else None, "+".join(origem) or "nenhuma")


def paleta_do_pedido(marca_hex, apoio_hex, gosto, anterior_hex=None, variar=False):
    """Fundo pelo gosto do executivo (claro/escuro) ou, sem gosto, na cor da marca (estilo JH).
    Destaque = cor de apoio do site quando legível, senão a própria marca. Nunca matiz inventado."""
    import random
    marca = _rgb(marca_hex)
    apoio = _rgb(apoio_hex) if apoio_hex else None
    claros = [("fundo branco", (255, 255, 255)), ("fundo claro neutro", (247, 248, 250)),
              ("fundo claro na cor da marca", _misturar(marca, (255, 255, 255), 0.9)),
              ("fundo creme", (250, 247, 240))]
    escuros = [("fundo grafite", (28, 28, 30)), ("fundo marca escura", _misturar(marca, (0, 0, 0), 0.6))]
    na_marca = [("fundo na cor da marca", marca)] + ([("fundo na cor de apoio do site", apoio)] if apoio else [])
    if gosto == "claro":
        opcoes = claros
    elif gosto == "escuro":
        opcoes = escuros
    else:
        opcoes = na_marca + (claros[:2] + escuros[:1] if variar else [])
    anterior = anterior_hex.upper() if anterior_hex else None
    restantes = [o for o in opcoes if _hex(o[1]) != anterior] or opcoes
    nome, fundo = random.choice(restantes) if variar else restantes[0]
    claro = _lum(fundo) > 0.4
    destaque = None
    for cor in ([marca, apoio] if fundo != marca else [apoio]):
        if cor and _contraste(cor, fundo) >= 3:
            destaque = cor
            break
    if destaque is None:
        destaque = _legivel_sobre(marca if fundo != marca else (apoio or (255, 255, 255)), fundo)
    neutra = (16, 20, 24) if claro else (247, 248, 250)
    return nome, {"principal": _hex(fundo), "destaque": _hex(destaque), "neutra": _hex(neutra)}


def gerar_pecas_paleta(caminho, logo, cliente, segmento, paleta):
    import atendimento
    pasta = Path(caminho).parent
    embrulho = pasta / "embrulho_paleta.py"
    embrulho.write_text(EMBRULHO_PALETA, encoding="utf-8")
    comando = [sys.executable, str(embrulho), str(atendimento.GERADOR), json.dumps(paleta), "auto",
               "--logo", str(logo), "--nome", cliente,
               "--segmento", segmento or atendimento.SEGMENTO_PADRAO,
               "--catalogo", str(caminho), "--regua-logo", "portal",
               "--candidatas", "0", "--so-fallback", "--cor", paleta["principal"]]
    return atendimento._rodar_gerador(comando, atendimento.prefixo(Path(caminho).name))


def gerar_pecas_simples(caminho, logo, cliente, segmento, cor=None):
    """Banner no estilo da JH: painel com a logo e a paleta do cliente, sem cena
    desenhada por IA (a cena gerada deformava produto: bicicleta sem guidão).
    --candidatas 0 não gera cena nenhuma; --so-fallback monta só o piso."""
    import atendimento
    comando = [sys.executable, str(atendimento.GERADOR), "auto",
               "--logo", str(logo), "--nome", cliente,
               "--segmento", segmento or atendimento.SEGMENTO_PADRAO,
               "--catalogo", str(caminho), "--regua-logo", "portal",
               "--candidatas", "0", "--so-fallback"]
    if cor:
        comando += ["--cor", cor]
    return atendimento._rodar_gerador(comando, atendimento.prefixo(Path(caminho).name))


NOMES_DE_COR = {"laranja": "#F26B1D", "vermelh": "#D62828", "azul": "#1F5FBF", "amarel": "#F2B705",
                "roxo": "#6A3FB5", "rosa": "#E0457B", "vinho": "#7A1F3D", "marsala": "#7A1F3D",
                "verde": "#1E8C4E", "preto": "#1C1C1E", "cinza": "#6B7280", "marrom": "#7B4B2A", "dourad": "#C9A227"}


def cor_pedida(texto):
    """Cor que o executivo mandou USAR ("coloque laranja", "a cor deles é azul"); ignora
    as que ele mandou tirar ("tira esse verde", "sem marsala")."""
    t = _texto_simples(texto)
    for trecho in re.split(r"[,.;]| e ", t):
        if re.search(r"\b(tir|sem|nao|remov|evit|inves|desse|dessa|esse|essa|horr|feio)", trecho):
            continue
        for nome, hexa in NOMES_DE_COR.items():
            if nome in trecho and nome not in ("preto",):
                return hexa
    return None


def gerar_com_identidade(entrada, caminho, logo, variar=False, anterior=None, texto=""):
    """Banners na identidade do cliente (logo + site) e no gosto do executivo."""
    marca, apoio, origem = identidade_visual(entrada.get("site"), logo)
    pedida = cor_pedida(texto)
    if pedida and (not marca or _dist_matiz(_rgb(pedida), _rgb(marca)) > 25):
        apoio, marca, origem = marca, pedida, "pedido do usuário"
    if not marca:
        marca = entrada.get("cor") or COR_LOGO_CLARA
        origem = "padrão (logo sem cor e site sem cor de marca)"
    atual = _texto_simples(texto)
    gosto = ("claro" if any(p in atual for p in PALAVRAS_CLARO) else
             "escuro" if any(p in atual for p in PALAVRAS_ESCURO) else "")
    fonte_gosto = "pedido agora"
    if not gosto:
        gosto = gosto_do_executivo(entrada.get("preferencias"))
        fonte_gosto = "histórico do executivo"
    if not gosto and logo_clara(logo):
        gosto, fonte_gosto = "escuro", "logo clara"
    nome, paleta = paleta_do_pedido(marca, apoio, gosto, anterior, variar)
    evento("banners", f"identidade: marca {marca}" + (f", apoio {apoio}" if apoio else "") + f" (de {origem}); "
                      f"{nome} {paleta['principal']}, destaque {paleta['destaque']}"
                      + (f"; gosto {gosto} ({fonte_gosto})" if gosto else ""))
    nova, saida = gerar_pecas_paleta(caminho, logo, entrada.get("cliente") or "", entrada.get("segmento"), paleta)
    if nova:
        arquivo = Path(nova) / "paleta.json"
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            dados["marca"] = marca
            arquivo.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            pass
    return nova, saida, paleta


def previa(entrada):
    import atendimento
    pedido_id = entrada["pedido_id"]
    pasta = pasta_pedido(pedido_id)
    logo = restaurar_logo(entrada, pasta)
    if not logo:
        try:
            logo = logo_tipografica(entrada.get("cliente"), pasta)
            evento("banners", "sem logo: usando logo de texto gerada pelo nome do cliente", "aviso")
        except Exception as erro:
            return {"sem_banner": f"sem logo e a logo de texto falhou ({type(erro).__name__}: {erro})"}
    caminho = gravar_catalogo(entrada["catalogo"], pedido_id)
    evento("banners", "gerando as peças (login e cabeçalho)")
    gerada, saida, _ = gerar_com_identidade(entrada, caminho, logo, variar=False)
    if not gerada:
        return {"sem_banner": str(saida)[-800:]}
    return {"pecas": pecas_para_tela(gerada), "cor": cor_da_pasta(gerada),
            "banners_tar": empacotar(gerada), "gerador": str(saida)[-1500:]}


def renovar_imagens_do_anexo(catalogo):
    """Imagem tirada do anexo mora em resource-files com URL assinada de ~2h:
    pede URL nova pelo file_id antes de criar o portal."""
    pedidos = [r for e in catalogo.get("etapas") or [] if e.get("endpoint") == "products"
               for r in e.get("requests") or [] if r.get("_file_id")]
    if not pedidos:
        return
    import anexo
    hospedagem = anexo.Hospedagem()
    for r in pedidos:
        r["temp_image_url"] = hospedagem.renovar(r["_file_id"])
    evento("criacao", f"{len(pedidos)} imagens do anexo com URL renovada")


def miniaturas(entrada):
    """Pedido antigo sem miniatura: renova a URL pelo file_id e grava a miniatura no catálogo."""
    import requests
    import anexo
    catalogo = entrada["catalogo"]
    pedidos = [r for e in catalogo.get("etapas") or [] if e.get("endpoint") == "products"
               for r in e.get("requests") or [] if r.get("_file_id") and not r.get("_miniatura")]
    if pedidos:
        hospedagem = anexo.Hospedagem()
        for r in pedidos:
            r["temp_image_url"] = hospedagem.renovar(r["_file_id"])
            r["_miniatura"] = anexo.miniatura(requests.get(r["temp_image_url"], timeout=60).content)
    return {"catalogo": catalogo, "atualizados": len(pedidos)}


def criar(entrada):
    import atendimento
    pedido_id = entrada["pedido_id"]
    pasta = pasta_pedido(pedido_id)
    logo = restaurar_logo(entrada, pasta)
    banners = restaurar_banners(entrada, pasta)
    renovar_imagens_do_anexo(entrada["catalogo"])
    caminho = gravar_catalogo(entrada["catalogo"], pedido_id)
    simular = bool(entrada.get("simular"))
    evento("criacao", "simulação: valida sem criar nada" if simular else "criando o portal na org pocs")
    resultado = atendimento.atender(caminho, logo, ORG, True, pedido_id=pedido_id,
                                    origem_id=pedido_id, simular=simular)
    saida = {"resultado": resultado}
    if resultado.get("status") == "concluido" and banners:
        try:
            evento("banners", "publicando as peças no portal (ainda não aplicadas)")
            saida["publicadas"] = atendimento.publicar_pecas(ORG, resultado["portal_id"], banners)
        except Exception as erro:
            saida["publicar_erro"] = f"{type(erro).__name__}: {erro}"
    return saida


def banner(entrada):
    import atendimento
    pedido_id, acao = entrada["pedido_id"], entrada["acao_banner"]
    pasta = pasta_pedido(pedido_id)
    banners = restaurar_banners(entrada, pasta)
    portal_id = entrada.get("portal_id")
    if acao == "aplicar":
        cor = cor_da_pasta(banners) if banners else None
        try:
            relato = atendimento.aplicar_pecas(ORG, portal_id, entrada["escolhas"], cor=cor)
        except atendimento.GravacaoPelaMetade as erro:
            return {"aplicado_parcial": True, "gravados": erro.gravados,
                    "faltou": erro.faltou, "erro": str(erro)}
        return {"relato": relato}
    if not banners:
        raise RuntimeError("este pedido não tem pasta de banners para refazer")
    if acao == "regerar":
        pecas = entrada["pecas"]
        feedback = entrada.get("feedback")
        if isinstance(feedback, str):
            feedback = {peca: feedback.strip() for peca in pecas} if feedback.strip() else None
        logo = restaurar_logo(entrada, pasta)
        if not logo:
            logo = logo_tipografica(entrada.get("cliente"), pasta)
        texto = "; ".join(sorted(set(feedback.values()))) if feedback else ""
        anterior = None
        try:
            anterior = json.loads((Path(banners) / "paleta.json").read_text(encoding="utf-8")).get("principal")
        except (OSError, ValueError):
            pass
        if texto:
            evento("banners", "pedido de mudança: " + texto[:200])
        caminho = gravar_catalogo(entrada["catalogo"], pedido_id)
        nova, saida, _ = gerar_com_identidade(entrada, caminho, logo, variar=True, anterior=anterior, texto=texto)
    elif acao == "recolorir":
        pecas = list(atendimento.DESTINOS_BANNER)
        nova, saida = atendimento.repintar_pecas(banners, entrada["cor"])
    else:
        raise RuntimeError(f"ação de banner desconhecida: {acao}")
    if not nova:
        raise RuntimeError(str(saida)[-800:])
    resposta = {"pecas": pecas_para_tela(nova, set(pecas)), "cor": cor_da_pasta(nova),
                "banners_tar": empacotar(nova)}
    if portal_id:
        resposta["publicadas"] = atendimento.publicar_pecas(ORG, portal_id, nova, set(pecas))
    return resposta


ACOES = {"trocar_logo": trocar_logo, "miniaturas": miniaturas, "extrair": extrair, "avaliar": avaliar, "previa": previa, "criar": criar, "banner": banner}


def main():
    acao, arquivo_entrada, arquivo_saida = sys.argv[1:4]
    entrada = json.loads(Path(arquivo_entrada).read_text(encoding="utf-8"))
    try:
        resultado = {"ok": True, **ACOES[acao](entrada)}
    except Exception as erro:
        resultado = {"ok": False, "erro": f"{type(erro).__name__}: {erro}",
                     "rastro": traceback.format_exc()[-2500:]}
    Path(arquivo_saida).write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

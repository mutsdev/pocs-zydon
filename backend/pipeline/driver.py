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
import random
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


def _proteger_logo_opaca():
    """Logo sem transparência (JPG, foto de perfil) nunca vira silhueta chapada: pintar a
    imagem inteira de uma cor só gera um retângulo preto no cabeçalho do portal."""
    try:
        import logo as mod_logo
    except Exception:
        return
    original = mod_logo.preparar_para_fundo
    if getattr(original, "_protegida", False):
        return

    def preparar_para_fundo(logo_img, fundo, limiares):
        pronta, modo = original(logo_img, fundo, limiares)
        if modo.get("modo") == "knockout":
            alfa = logo_img.convert("RGBA").getchannel("A")
            transparentes = sum(alfa.histogram()[:128])
            if transparentes < 0.05 * logo_img.width * logo_img.height:
                return logo_img, dict(modo, modo="original", motivo="logo sem transparência não vira silhueta")
        return pronta, modo
    preparar_para_fundo._protegida = True
    mod_logo.preparar_para_fundo = preparar_para_fundo


PROTECAO_NO_ARQUIVO = """

# --- protecao do pipeline_poc: logo opaca nunca vira silhueta chapada ---
_preparar_para_fundo_original = preparar_para_fundo


def preparar_para_fundo(logo, fundo, limiares):
    pronta, modo = _preparar_para_fundo_original(logo, fundo, limiares)
    if modo.get("modo") == "knockout":
        alfa = logo.convert("RGBA").getchannel("A")
        if sum(alfa.histogram()[:128]) < 0.05 * logo.width * logo.height:
            return logo, dict(modo, modo="original", motivo="logo sem transparencia nao vira silhueta")
    return pronta, modo
"""


def _proteger_logo_no_arquivo():
    """O cabeçalho do portal é montado em outro processo (runner da criação), onde a
    proteção em memória não vale: grava a mesma proteção no logo.py do repositório."""
    arquivo = REPO / "Identidade Visual" / "logo.py"
    try:
        texto = arquivo.read_text(encoding="utf-8")
        if "protecao do pipeline_poc" not in texto:
            arquivo.write_text(texto + PROTECAO_NO_ARQUIVO, encoding="utf-8")
    except OSError:
        pass


COR_PORTAL_NO_ARQUIVO = """

# --- protecao do pipeline_poc: cor clara da marca escurece no mesmo tom, nao vira preto ---
_cor_de_portal_original = cor_de_portal


def cor_de_portal(hexa, contraste_minimo=CONTRASTE_MINIMO_COR_PORTAL):
    rgb = de_hex(hexa)
    if contraste(BRANCO, rgb) >= contraste_minimo:
        return para_hex(rgb), None
    if max(rgb) - min(rgb) < 40:
        return _cor_de_portal_original(hexa, contraste_minimo)
    for passo in range(1, 20):
        peso = passo * 0.05
        escura = tuple(round(c * (1 - peso)) for c in rgb)
        if contraste(BRANCO, escura) >= contraste_minimo:
            return para_hex(escura), (f"a cor {para_hex(rgb)} era clara demais sobre o branco: "
                                      f"o portal vai no mesmo tom, mais escuro ({para_hex(escura)})")
    return _cor_de_portal_original(hexa, contraste_minimo)
"""


def _proteger_cor_no_arquivo():
    """Cor da marca clara demais (azul-claro da Nutrimental) virava PRETO no menu e nos
    botões do portal: escurece no mesmo tom até ter contraste. Cinza continua indo de preto."""
    arquivo = REPO / "Identidade Visual" / "cor.py"
    try:
        texto = arquivo.read_text(encoding="utf-8")
        if "protecao do pipeline_poc: cor clara" not in texto:
            arquivo.write_text(texto + COR_PORTAL_NO_ARQUIVO, encoding="utf-8")
    except OSError:
        pass


_proteger_logo_no_arquivo()
_proteger_cor_no_arquivo()
_proteger_logo_opaca()

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
    with Image.open(caminho) as bruta:
        bruta.draft("RGBA", (400, 400))
        miniatura = bruta.convert("RGBA")
    miniatura.thumbnail((400, 400))
    img = np.asarray(miniatura, dtype=np.float32)
    visivel = img[..., 3] > 128
    if not visivel.any():
        return False
    return float((img[..., :3][visivel] @ np.array([0.299, 0.587, 0.114])).mean()) > 215


def reduzir_imagem(caminho, lado=1600):
    """Logo gigante (milhares de px) estoura a memória nas etapas seguintes: reduz antes."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 80_000_000
    try:
        with Image.open(caminho) as img:
            if max(img.size) <= lado:
                return caminho
            img.draft("RGBA", (lado, lado))
            menor = img.convert("RGBA")
        menor.thumbnail((lado, lado), Image.LANCZOS)
        alvo = Path(caminho).with_name(Path(caminho).stem + "_reduzida.png")
        menor.save(alvo, "PNG")
        evento("extracao", f"logo grande reduzida para {menor.width}x{menor.height} (economia de memória)")
        return alvo
    except Exception:
        return caminho


def _logo_vazia(caminho):
    """Motivo quando a imagem não tem desenho de logo: transparente (imagem de espera do
    carregamento preguiçoso) ou retângulo chapado de uma cor só. None quando há desenho."""
    from PIL import Image
    import numpy as np
    with Image.open(caminho) as img:
        dados = np.asarray(img.convert("RGBA"), dtype=np.int16)
    opacos = dados[..., 3] > 40
    if opacos.sum() < max(30, opacos.size * 0.01):
        return "imagem transparente, sem desenho"
    cores = dados[..., :3][opacos]
    amostra = cores[:: max(1, len(cores) // 20000)] // 24
    _, contagem = np.unique(amostra, axis=0, return_counts=True)
    dominante = contagem.max() / len(amostra)
    ys, xs = np.where(opacos)
    preenchida = opacos.sum() / ((ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1))
    if dominante > 0.99 and preenchida > 0.85:
        return "retângulo chapado de uma cor só, sem desenho"
    return None


def _jpeg_sobre(caminho, fundo, largura=512):
    from PIL import Image
    with Image.open(caminho) as img:
        img = img.convert("RGBA")
        base = Image.new("RGB", img.size, fundo)
        base.paste(img, mask=img.split()[3])
    base.thumbnail((largura, largura))
    saida = io.BytesIO()
    base.save(saida, "JPEG", quality=85)
    return base64.b64encode(saida.getvalue()).decode()


def _ia_visao(texto, imagens):
    """Conferência visual: Gemini primeiro, barroso-chat de reserva. (resposta, ia) ou (None, motivos)."""
    conteudo, baixadas = [{"type": "text", "text": texto}], {}
    for i, (rotulo, dados) in enumerate(imagens):
        chave = f"local://conferencia/{i}"
        conteudo += [{"type": "text", "text": rotulo}, {"type": "image_url", "image_url": {"url": chave}}]
        baixadas[chave] = ("image/jpeg", dados)
    mensagens = [{"role": "user", "content": conteudo}]
    motivos = []
    for nome, chamar in (("Gemini", selecao._ia_gemini), ("barroso-chat", selecao._ia_barroso)):
        try:
            resposta, custo = chamar(mensagens, baixadas)
        except Exception as erro:
            motivos.append(f"{nome}: {type(erro).__name__}: {str(erro)[:120]}")
            continue
        selecao.registrar_modelo(custo.get("modelo"), custo.get("custo_usd") or 0.0)
        return resposta, nome
    return None, " · ".join(motivos)


INSTRUCAO_CONFERIR_LOGO = """Você confere a LOGO da empresa "{cliente}" que vai no cabeçalho de um portal B2B.
A mesma imagem aparece sobre fundo branco e sobre fundo escuro.
Reprove (ok=false) se a imagem: estiver vazia ou transparente; for um retângulo ou bloco de cor
chapada sem desenho; for ilegível, borrada ou cortada; for ícone genérico (lupa, carrinho, menu,
rede social, seta); for banner, foto de produto, selo ou logo de outra empresa.
Aprove (ok=true) quando for a marca da empresa (símbolo e/ou nome) legível em pelo menos um dos fundos.
Responda só JSON: {{"ok": true, "o_que_aparece": "nome Vitarella em vermelho", "motivo": ""}}"""


def conferir_logo_ia(caminho, cliente):
    """(aprovada, motivo). Sem IA disponível a logo segue (a régua de pixels já passou)."""
    imagens = [("Logo sobre fundo branco:", _jpeg_sobre(caminho, (255, 255, 255))),
               ("Logo sobre fundo escuro:", _jpeg_sobre(caminho, (40, 40, 44)))]
    resposta, ia = _ia_visao(INSTRUCAO_CONFERIR_LOGO.format(cliente=cliente or "cliente"), imagens)
    if resposta is None:
        evento("extracao", f"conferência visual da logo indisponível ({ia}); seguindo só com a régua de pixels", "aviso")
        return True, None
    aprovada = resposta.get("ok") is not False
    evento("extracao", f"conferência visual da logo ({ia}): {'aprovada' if aprovada else 'REPROVADA'} · "
                       f"{resposta.get('o_que_aparece') or ''} {resposta.get('motivo') or ''}".strip(),
           "info" if aprovada else "aviso")
    return aprovada, resposta.get("motivo") or resposta.get("o_que_aparece") or "não parece a logo"


def conferir_logo(logo, cliente=None):
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
        caminho = Path(reduzir_imagem(caminho))
        caminho = Path(recortar_circulo_de_perfil(caminho))
        vazia = _logo_vazia(caminho)
        if vazia:
            raise ValueError(vazia)
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
        if cliente:
            aprovada, motivo = conferir_logo_ia(caminho, cliente)
            if not aprovada:
                return None, f"a logo achada ({Path(str(logo)).name}) foi reprovada na conferência visual: {motivo}"
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
    import numpy as np
    dados = np.array(img)
    dentro = dados[..., 3] > 0
    quase_branco = (dados[..., :3].min(axis=2) > 225) & dentro
    if dentro.sum() and quase_branco.sum() / dentro.sum() > 0.4:
        dados[quase_branco, 3] = 0
        img = Image.fromarray(dados, "RGBA")
        caixa = img.getbbox()
        if caixa:
            img = img.crop(caixa)
        evento("extracao", "foto de perfil: fundo branco do círculo removido, fica só a marca")
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


def _logo_pelo_nome(soup, base, cliente):
    """Logo sem 'logo' no arquivo nem na classe (mabel.com.br: <img src=".../mabel.png" alt="Mabel">):
    imagem do cabeçalho cujo alt ou nome de arquivo é o nome do cliente."""
    from urllib.parse import urljoin
    palavras = [p for p in re.findall(r"[a-z0-9]{3,}", _sem_acento(cliente or ""))
                if p not in {"ltda", "distribuidora", "comercio", "industria", "atacado", "biscoitos", "alimentos"}]
    if not palavras:
        return ""
    for img in soup.find_all("img")[:15]:
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        if re.search(r"(?i)slider|carousel|banner|/produtos?/|/receitas?/|/cache/", src):
            continue
        arquivo = _sem_acento(src.split("?")[0].rsplit("/", 1)[-1])
        alt = _sem_acento(img.get("alt") or "")
        if any(p in arquivo or alt.strip() == p for p in palavras[:2]):
            return urljoin(base, src)
    return ""


def _logo_da_home(site, cliente=""):
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
    return _logo_pelo_arquivo(soup, final) or _logo_pelo_nome(soup, final, cliente)


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
    palavras = [p for p in re.findall(r"[a-z0-9]{2,}", nome)
                if p not in {"ltda", "distribuidora", "distribuidor", "distribuidores", "distribuicao", "comercio",
                             "industria", "teste", "anexo", "loja", "atacado", "atacadista", "me", "eireli", "sa"}]
    if not palavras:
        return "", ""
    informado = (urlparse(selecao.normalizar_site(site_informado)).hostname or "") if site_informado else ""
    vistos = set()
    for consulta in (f"{cliente} site oficial",):
        for url in selecao.buscar_barroso(consulta, 8) or selecao.buscar_duckduckgo(consulta, 8) or selecao.buscar_bing(consulta, 8):
            host = (urlparse(url).hostname or "").lower()
            if not host or host == informado or selecao.MERCADO_LIVRE.search(host):
                continue
            if not all(p in host.replace("-", "") for p in palavras[:3]):
                continue
            base = f"https://{host}/"
            if base in vistos:
                continue
            vistos.add(base)
            if nomes_produtos and not _home_fala_dos_produtos(base, nomes_produtos):
                continue
            achada = _logo_da_home(base, cliente)
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


PRAZO_BUSCA_SEGUNDOS = 140


def _logo_inicial(entrada):
    """Logo do site (ou do Instagram), procurada em paralelo com a busca de produtos:
    não depende do catálogo. (logo, url, origem, aviso)."""
    import atendimento
    site = entrada.get("site")
    if not site:
        return None, None, None, None
    nav = entrada.get("_navegador") or {}
    if nav.get("logo_arquivo"):
        logo, aviso_logo = conferir_logo(nav["logo_arquivo"], entrada.get("cliente"))
        if not logo and nav.get("logo_recorte") and nav["logo_recorte"] != nav["logo_arquivo"]:
            logo, aviso_logo = conferir_logo(nav["logo_recorte"], entrada.get("cliente"))
        if logo:
            evento("extracao", "logo do site encontrada pelo navegador (apontada pelo barroso-chat na captura)")
            return logo, nav.get("logo_url"), "navegador", aviso_logo
        evento("navegador", f"logo apontada na captura não passou na régua ({aviso_logo}); tentando pelo código da página", "aviso")
    logo_url = _logo_da_home(site, entrada.get("cliente"))
    if not logo_url:
        return None, None, None, None
    original = selecao._imagem_cheia(logo_url)
    if original != logo_url:
        evento("extracao", "logo do Wix: usando o arquivo original (a versão da página vem em AVIF)")
        logo_url = original
    prefixo = atendimento.prefixo(nome_arquivo(entrada.get("cliente"), entrada.get("pedido_id")))
    bruta = atendimento.baixar_logo(logo_url, prefixo)
    logo, aviso_logo = conferir_logo(bruta, entrada.get("cliente"))
    if logo:
        evento("extracao", "logo do site encontrada (em paralelo com a busca de produtos)")
        return logo, logo_url, "site", aviso_logo
    if bruta and re.search(r"instagram\.com/", site):
        evento("extracao", "logo = foto de perfil do Instagram, usada mesmo pequena (não passou na régua)")
        return str(foto_de_perfil_como_logo(bruta)), logo_url, "instagram", None
    return None, logo_url, None, aviso_logo


def montar_catalogo(entrada, ao_ter_candidatos=None):
    """Coleta, filtra, seleciona por IA e monta. Levanta PrecisaCatalogo."""
    cliente, site = entrada["cliente"], str(entrada.get("site") or "").strip()
    selecao.iniciar_prazo(PRAZO_BUSCA_SEGUNDOS)
    segmento_informado = str(entrada.get("segmento") or "").strip()
    observacao = str(entrada.get("foco") or "").strip()
    quantos, sem_quantidade = selecao.quantidade_pedida(observacao)
    selecao.QUANTOS["n"] = quantos
    foco, eixo_pedido = selecao.separar_observacao(sem_quantidade)
    if not selecao.partes_do_foco(foco):
        foco = ""
    if quantos:
        evento("extracao", f"quantidade pedida na observação: {quantos} produtos")
    if observacao:
        evento("extracao", f"observação do pedido: {observacao}"
               + (f" · variação pedida: {eixo_pedido}" if eixo_pedido else ""))
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
    pelo_barroso = False
    if entrada.get("barroso_tudo") and not entrada.get("anexo"):
        sugeridos, segmento_barroso = selecao.produtos_pelo_barroso(cliente, site, observacao, selecao.alvo_pedido())
        achados, descartes_barroso = selecao.filtrar_candidatos(sugeridos)
        descartes += descartes_barroso
        evento("extracao", f"modo barroso-chat: {len(achados)} produtos com página e foto válidas")
        if achados:
            validos, pelo_barroso = achados, True
            coleta["plataforma"] = "barroso-chat"
            if not segmento_informado and segmento_barroso:
                segmento_informado = segmento_barroso
            if ao_ter_candidatos:
                ao_ter_candidatos([v["nome"] for v in achados[:selecao.alvo_pedido()]], segmento_informado)
        else:
            evento("extracao", "modo barroso-chat não trouxe produto válido; seguindo a busca normal", "aviso")
        if not pelo_barroso:
            selecao.iniciar_prazo(PRAZO_BUSCA_SEGUNDOS)
        if not tipos_da_empresa and selecao.BARROSO_INFO["tipos"]:
            tipos_da_empresa = list(selecao.BARROSO_INFO["tipos"])
            evento("extracao", "o que a empresa vende, segundo a pesquisa na web: "
                   + (selecao.BARROSO_INFO["o_que_vende"] or ", ".join(tipos_da_empresa)))
    if entrada.get("anexo"):
        import anexo
        evento("extracao", f"lendo o anexo {entrada['anexo']['nome']}")
        fonte_anexo, do_anexo, descartes_anexo = anexo.candidatos_do_anexo(
            entrada["anexo"]["nome"], entrada["anexo"]["conteudo_base64"])
        validos, descartes_filtro = selecao.filtrar_candidatos(do_anexo)
        descartes += descartes_anexo + descartes_filtro
        coleta["plataforma"] = fonte_anexo
        evento("extracao", f"anexo: {len(validos)} produtos válidos")
    do_navegador = (entrada.get("_navegador") or {}).get("candidatos") or []
    if do_navegador:
        from urllib.parse import urlparse as _up
        brutos = [selecao.candidato(c["nome"], c["url"], c["imagem"], c.get("preco"), c.get("categoria"), "", "site")
                  for c in do_navegador if _up(c.get("url") or "").path.strip("/")]
        aceitos, descartes_nav = selecao.filtrar_candidatos(brutos)
        vistos = {selecao.sem_acento(v["nome"]) for v in validos}
        novos = [v for v in aceitos if selecao.sem_acento(v["nome"]) not in vistos]
        validos += novos
        descartes += descartes_nav
        if coleta.get("plataforma") in (None, "nenhuma"):
            coleta["plataforma"] = "navegador"
        evento("extracao", f"navegador: {len(novos)} candidatos válidos das páginas de produtos, "
                           f"{len(descartes_nav)} descartados")
    if site and not pelo_barroso and len(validos) < selecao.MAXIMO_PRODUTOS:
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
    if site and not pelo_barroso and len(validos) < selecao.MAXIMO_PRODUTOS:
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
    if site and not pelo_barroso and len(validos) < selecao.MAXIMO_PRODUTOS:
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
    if not pelo_barroso and len(validos) < selecao.minimo_pedido() and not tipos_da_empresa and not fonte_anexo:
        tipos_da_empresa = selecao.descobrir_empresa(cliente, site).get("tipos") or []
        if tipos_da_empresa:
            evento("extracao", "produtos que a empresa vende, segundo o Google: " + ", ".join(tipos_da_empresa))
    ja_buscou = {"web": False}

    def buscar_pela_web(validos, motivo):
        ja_buscou["web"] = True
        evento("extracao", f"{motivo}: buscando na web produtos do mesmo tipo")
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
        if len(brutos) < selecao.minimo_pedido() * 2:
            brutos += selecao.buscar_candidatos(cliente, segmento_informado)
        achados, descartes_busca = selecao.filtrar_candidatos(brutos)
        vistos = {v["imagem"] for v in validos} | {selecao.sem_acento(v["nome"]) for v in validos}
        novos = [a for a in achados if a["imagem"] not in vistos and selecao.sem_acento(a["nome"]) not in vistos]
        evento("extracao", f"busca na web: +{len(novos)} candidatos válidos")
        return novos, descartes_busca

    do_foco = [v for v in validos if selecao.casa_com_foco(v, foco)] if foco else validos
    if foco:
        evento("extracao", f"{len(do_foco)} dos {len(validos)} candidatos do site são do foco pedido "
                           f"({', '.join(selecao.partes_do_foco(foco)) or foco})")
    if not pelo_barroso and (len(validos) < selecao.minimo_pedido() or (foco and len(do_foco) < selecao.alvo_pedido())):
        motivo = (f"site com só {len(validos)} produtos" if len(validos) < selecao.minimo_pedido()
                  else f"só {len(do_foco)} produtos do foco no site")
        novos, descartes_busca = buscar_pela_web(validos, motivo)
        validos += novos
        descartes += descartes_busca
    if foco:
        casam = [v for v in validos if selecao.casa_com_foco(v, foco)]
        validos = casam + [v for v in validos if not selecao.casa_com_foco(v, foco)]
    validos = validos[:selecao.MAXIMO_CANDIDATOS]

    def conferir(lista):
        if not lista:
            return []
        evento("extracao", f"IA (fila gratuita) conferindo as fotos dos {len(lista)} "
                           "candidatos")
        aprovados, descartes_fotos, custo_fotos = selecao.conferir_ate(lista, cliente, alvo=len(lista))
        for k in ("custo_usd", "tokens_entrada", "tokens_saida"):
            custo[k] += custo_fotos.get(k) or 0
        descartes.extend(descartes_fotos)
        return aprovados

    def sem_repetidos(lista):
        unicos, nomes = [], set()
        for v in lista:
            chave = selecao.chave_produto(v["nome"])
            if chave in nomes:
                descartes.append({"nome": v["nome"], "motivo": "duplicado (mesmo produto escrito de outro jeito)"})
                continue
            nomes.add(chave)
            unicos.append(v)
        return unicos

    if pelo_barroso:
        evento("extracao", "modo barroso-chat: fotos tiradas da própria página do produto; "
                           "a seleção olha as imagens, sem conferência separada")
        validos = sem_repetidos(validos)
    else:
        validos = sem_repetidos(conferir(validos))
    if len(validos) < selecao.minimo_pedido() and not ja_buscou["web"]:
        novos, descartes_busca = buscar_pela_web(
            validos, f"só {len(validos)} produtos passaram na conferência das fotos")
        descartes += descartes_busca
        validos = sem_repetidos(validos + conferir(novos[:selecao.MAXIMO_CANDIDATOS]))
    validos = sorted(validos, key=lambda v: not v.get("foto_conferida"))
    confirmados = [v["nome"] for v in validos if v.get("foto_conferida")]
    if ao_ter_candidatos and len(confirmados) >= min(3, selecao.alvo_pedido()):
        ao_ter_candidatos(confirmados[:selecao.alvo_pedido()], segmento_informado)
    if len(validos) < selecao.minimo_pedido():
        evento("extracao", f"só {len(validos)} produtos confirmados no site e na web; o portal segue com eles "
                           "e o pedido registra que o catálogo ficou curto", "aviso")
        entrada["_aviso_curto"] = (f"catálogo curto: só {len(validos)} produtos confirmados no site e na web; "
                                   "anexe um PDF ou planilha se quiser mais")
    if not validos or (entrada.get("automatico") and len(validos) < selecao.MINIMO_PRODUTOS):
        raise selecao.PrecisaCatalogo(
            f"só {len(validos)} produtos com URL de origem e imagem válida "
            f"{'no anexo, ' if fonte_anexo else ''}no site e na busca "
            f"(mínimo {selecao.MINIMO_PRODUTOS}); "
            + ("o anexo precisa ter nome e foto de cada produto; mande outro PDF ou planilha"
               if fonte_anexo else "mande o catálogo em PDF ou planilha"),
            {"custo": custo, "descartes": descartes})
    if entrada.get("licoes"):
        evento("extracao", f"usando {len(entrada['licoes'])} lições das avaliações anteriores na seleção")
    evento("extracao", f"IA (fila gratuita) escolhendo entre {len(validos)} candidatos")
    escolha, custo_selecao = _selecionar_com_teto(validos, cliente, site or f"anexo {fonte_anexo}",
                                                  segmento_informado, foco, entrada.get("licoes") or [])
    for k in ("custo_usd", "tokens_entrada", "tokens_saida"):
        custo_selecao[k] = (custo_selecao.get(k) or 0) + (custo.get(k) or 0)
    custo = _custo_total(custo_selecao)
    evento("extracao", f"seleção: {len(escolha.get('selecionados') or [])} produtos, "
                       f"custo US$ {custo['custo_usd']:.4f}")
    segmento_modelo = str(escolha.get("segmento") or "").strip()
    try:
        catalogo, precos, situacao, similares, regra_preco, descartes_modelo = selecao.montar_pela_selecao(
            coleta, validos, escolha, cliente, segmento_informado or segmento_modelo,
            entrada.get("descricao"), com_variacoes=bool(entrada.get("variacoes")), eixo_pedido=eixo_pedido)
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
    if entrada.get("automatico") and len(precos) < selecao.MINIMO_PRODUTOS:
        raise selecao.PrecisaCatalogo(
            f"só {len(precos)} produtos reais depois da seleção (mínimo {selecao.MINIMO_PRODUTOS} no Dexter); "
            "mande o catálogo em PDF ou planilha", {"custo": custo, "descartes": descartes})
    if ao_ter_candidatos and precos:
        ao_ter_candidatos([p["nome"] for p in precos], segmento_informado or segmento_modelo)
    return {"catalogo": catalogo, "precos": precos, "preco": situacao, "similares": similares,
            "regra_preco": regra_preco, "candidatos": validos,
            "custo": custo, "descartes": descartes, "segmento_modelo": segmento_modelo,
            "candidatos_validos": len(validos),
            "nomes_lidos_na_imagem": sum(1 for p in precos if p.get("nome_lido_na_imagem")),
            "fonte": (("pdf" if fonte_anexo == "pdf" else "planilha") if any(p["fonte"] == "anexo" for p in precos)
                      else "busca" if any(p["fonte"] == "busca" for p in precos) else "site")}


TETO_SELECAO = 35


def _selecionar_com_teto(validos, cliente, site, segmento, foco, licoes=None):
    """Seleção pela IA com teto: sem resposta em TETO_SELECAO s, segue com os primeiros
    candidatos já validados (fotos e páginas conferidas), espalhados pelas categorias."""
    import threading
    caixa = {}

    def rodar():
        try:
            caixa["ok"] = selecao.selecionar(validos, cliente, site, segmento, foco, licoes)
        except Exception as erro:  # noqa: BLE001
            caixa["erro"] = erro

    fio = threading.Thread(target=rodar, daemon=True)
    fio.start()
    fio.join(TETO_SELECAO)
    if "ok" in caixa:
        return caixa["ok"]
    motivo = f"falhou ({caixa['erro']})" if "erro" in caixa else f"não respondeu em {TETO_SELECAO}s"
    evento("extracao", f"seleção pela IA {motivo}; seguindo com os primeiros candidatos validados", "aviso")
    categorias = []
    for c in validos:
        nome = str(c.get("categoria") or "").strip()
        if nome and nome not in categorias:
            categorias.append(nome)
    categorias = categorias[:3]
    selecionados = []
    for n, c in enumerate(validos[:selecao.alvo_pedido()]):
        nome = str(c.get("categoria") or "").strip()
        ci = categorias.index(nome) if nome in categorias else n % 3
        selecionados.append({"n": n, "categoria": ci, "do_cliente": c.get("origem") in ("site", "anexo"),
                             "no_foco": True})
    escolha = {"segmento": segmento or "", "categorias": categorias, "selecionados": selecionados,
               "descartados": []}
    return escolha, {"custo_usd": 0, "tokens_entrada": 0, "tokens_saida": 0, "modelo": "reserva sem IA"}


def _custo_total(custo):
    """Custo da fila + o que foi pago fora dela (busca do gateway); modelo = todos os usados."""
    custo = dict(custo)
    custo["custo_usd"] = round((custo.get("custo_usd") or 0) + selecao.CUSTO_EXTRA["custo_usd"], 6)
    if selecao.MODELOS_USADOS:
        custo["modelo"] = " + ".join(selecao.MODELOS_USADOS)[:200]
    return custo


def _banner_antecipado(entrada, logo_futura, nomes, segmento=""):
    """Banner feito assim que a logo e os produtos do site existem, sem esperar a curadoria."""
    import atendimento
    try:
        logo = logo_futura.result(timeout=60)[0]
    except Exception:
        return None
    if not logo:
        return None
    catalogo = {"empresa": entrada.get("cliente"), "etapas": [
        {"endpoint": "products", "requests": [{"label": n, "payload": {"name": n}} for n in nomes]}]}
    caminho = atendimento.DESTINO_JSON / ("previa_" + nome_arquivo(entrada.get("cliente"), entrada.get("pedido_id")))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(catalogo, ensure_ascii=False), encoding="utf-8")
    evento("banners", f"gerando as peças com {len(nomes)} produtos confirmados na cena, em paralelo com o fim da busca")
    gerada, _, _ = gerar_com_identidade(dict(entrada, segmento=segmento or entrada.get("segmento")),
                                        caminho, logo, variar=False)
    if not gerada:
        return None
    return {"logo": logo, "pecas": pecas_para_tela(gerada), "cor": cor_da_pasta(gerada),
            "banners_tar": empacotar(gerada)}


def _explorar_no_navegador(entrada):
    """Navegador sem tela como fonte principal: roda sozinho (antes da busca, para não
    disputar memória), o barroso-chat lê a captura e as cores achadas viram as cores do site."""
    import hashlib
    import navegador
    site = selecao.normalizar_site(entrada["site"])
    try:
        nav = navegador.explorar(site, entrada.get("cliente") or "", pasta_pedido(entrada["pedido_id"]),
                                 evento, selecao._ia_barroso)
    except Exception as erro:
        evento("navegador", f"navegador falhou ({type(erro).__name__}: {str(erro)[:200]}); "
                            "seguindo com a leitura do código da página", "aviso")
        return {}
    custo = nav.get("custo") or {}
    selecao.registrar_modelo(custo.get("modelo"), custo.get("custo_usd"))
    if nav.get("cores"):
        guardado = TRABALHO / "cores" / (hashlib.md5(("v2:" + entrada["site"].strip().lower()).encode()).hexdigest() + ".json")
        guardado.parent.mkdir(parents=True, exist_ok=True)
        guardado.write_text(json.dumps([list(_rgb(c)) for c in nav["cores"]]), encoding="utf-8")
        evento("navegador", "cores da marca pela captura: " + " / ".join(nav["cores"]))
    return nav


def extrair(entrada):
    import atendimento
    pedido_id = entrada["pedido_id"]
    observacoes = []
    if entrada.get("navegador") and entrada.get("site"):
        entrada["_navegador"] = _explorar_no_navegador(entrada)
    from concurrent.futures import ThreadPoolExecutor
    paralelo = ThreadPoolExecutor(2)
    logo_futura = paralelo.submit(_logo_inicial, entrada)
    cores_futuras = paralelo.submit(cores_do_site, entrada.get("site")) if entrada.get("site") else None
    paralelo.shutdown(wait=False)
    import threading
    import time
    banner = {}

    def iniciar_banner(nomes, segmento=""):
        if banner.get("fio") or entrada.get("sem_banner_antecipado"):
            return

        def rodar():
            try:
                banner["saida"] = _banner_antecipado(entrada, logo_futura, nomes, segmento)
            except Exception as erro:
                evento("banners", f"banner antecipado falhou ({type(erro).__name__}); refaço depois", "aviso")
        banner["inicio"] = time.monotonic()
        banner["fio"] = threading.Thread(target=rodar, daemon=True)
        banner["fio"].start()
    try:
        montado = montar_catalogo(entrada, iniciar_banner)
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
    if entrada.get("_aviso_curto"):
        observacoes.append(entrada["_aviso_curto"])
    if montado["similares"]:
        observacoes.append("há produtos SIMILARES achados na busca que NÃO são da marca do cliente")
        evento("extracao", "produtos similares de outras marcas no catálogo", "aviso")

    try:
        logo, logo_url, logo_origem, aviso_logo = logo_futura.result(timeout=90)
    except Exception as erro:
        logo, logo_url, logo_origem, aviso_logo = None, None, None, None
        evento("extracao", f"busca da logo no site falhou ({type(erro).__name__}); tentando pela web", "aviso")
    if cores_futuras is not None:
        try:
            cores_futuras.result(timeout=30)
        except Exception:
            pass
    if not logo:
        site_achado, logo_web = logo_pela_web(entrada.get("cliente"), entrada.get("site"),
                                                  [p["nome"] for p in precos])
        if logo_web:
            baixada = atendimento.baixar_logo(logo_web, atendimento.prefixo(caminho.name))
            baixada, aviso_web = conferir_logo(baixada, entrada.get("cliente"))
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
    saida["cores_navegador"] = (entrada.get("_navegador") or {}).get("cores") or None
    avisos_logo = [o for o in observacoes if "logo" in o]
    saida["logo_aviso"] = " · ".join(avisos_logo)[:800] or None
    if banner.get("fio") and banner["fio"].is_alive():
        evento("extracao", "produtos prontos para a curadoria; o banner termina em seguida")
        print("PARCIAL " + json.dumps(saida, ensure_ascii=False), flush=True)
    if banner.get("fio"):
        banner["fio"].join(timeout=max(5, 240 - (time.monotonic() - banner["inicio"])))
        pronto = banner.get("saida")
        if pronto and logo and Path(pronto.pop("logo")).resolve() == Path(logo).resolve():
            saida["banner"] = pronto
            evento("banners", "banners prontos junto com a curadoria")
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
feedback = paleta.pop("_feedback", None)
lab = paleta.pop("_lab", None)
sys.path.insert(0, str(gerador.parent))
sys.argv = [str(gerador)] + sys.argv[3:]
import gerar_banners
if feedback:
    _resolver = gerar_banners.mod_segmento.resolver
    def _resolver_com_pedido(*a, **k):
        contexto = _resolver(*a, **k)
        contexto["feedback"] = {"login": feedback, "cabecalho": feedback}
        return contexto
    gerar_banners.mod_segmento.resolver = _resolver_com_pedido
if lab:
    import tipografia as _tipo
    _ajustar_base = _tipo.ajustar
    def _ajustar_lab(desenho, texto, largura_max, corpo_inicial, corpo_minimo, *a, **k):
        return _ajustar_base(desenho, texto, largura_max, int(corpo_inicial * 1.18), int(corpo_minimo * 1.08), *a, **k)
    _tipo.ajustar = _ajustar_lab
import numpy as np
import logo as mod_logo
_preparar = mod_logo.preparar_para_fundo
def _colorida_visivel(img, fundo):
    dados = np.asarray(img.convert("RGBA"), dtype=np.float64).reshape(-1, 4)
    dados = dados[dados[:, 3] > 128][:, :3]
    if not len(dados):
        return False
    saturados = dados[(dados.max(axis=1) - dados.min(axis=1)) > 60]
    if len(saturados) < 0.1 * len(dados):
        return False
    def lum(c):
        c = c / 255.0
        c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]
    a, b = lum(saturados), float(lum(np.asarray(fundo, dtype=np.float64)))
    razao = (np.maximum(a, b) + 0.05) / (np.minimum(a, b) + 0.05)
    return float((razao >= 2.5).mean()) >= 0.6
def preparar_para_fundo(logo_img, fundo, limiares):
    pronta, modo = _preparar(logo_img, fundo, limiares)
    alfa = logo_img.convert("RGBA").getchannel("A")
    if modo.get("modo") == "knockout" and sum(alfa.histogram()[:128]) < 0.05 * logo_img.width * logo_img.height:
        return logo_img, dict(modo, modo="original", motivo="logo sem transparência não vira silhueta")
    if modo.get("modo") == "knockout" and _colorida_visivel(logo_img, fundo):
        return logo_img, dict(modo, modo="original", motivo="cor da marca visível no fundo")
    return pronta, modo
mod_logo.preparar_para_fundo = preparar_para_fundo
import fallback as mod_fallback
_tinta_original = mod_fallback._tinta_da_forma
def _tinta_da_forma(fundo_rgb):
    r, g, b = (float(c) for c in fundo_rgb[:3])
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    if lum <= 0.6 or max(r, g, b) - min(r, g, b) < 6:
        return _tinta_original(fundo_rgb)
    marca = [max(0.0, min(255.0, 255 + (c - 255) / 0.1)) for c in (r, g, b)]
    return tuple(int(round(c + (255 - c) * 0.4)) for c in marca)
mod_fallback._tinta_da_forma = _tinta_da_forma
original = gerar_banners.mod_paleta.extrair
def extrair(logo, cor_informada=None):
    base = original(logo, cor_informada)
    base.update(paleta)
    return base
gerar_banners.mod_paleta.extrair = extrair
import shutil, time
from concurrent.futures import ThreadPoolExecutor
import gerador as mod_gerador
import formatos as mod_formatos
import requests as _requests
_post = _requests.post
def _post_curto(*a, **k):
    k["timeout"] = min(float(k.get("timeout") or 40), 40)
    return _post(*a, **k)
_requests.post = _post_curto
mod_gerador.TENTATIVAS = 2
_avaliar = gerar_banners.juiz.avaliar
def _avaliar_rapido(imagem, contexto, config, tentativas=1):
    return _avaliar(imagem, contexto, config, 1)
gerar_banners.juiz.avaliar = _avaliar_rapido
_gerar_e_montar_original = gerar_banners._gerar_e_montar
def _encher_paralelo(pasta, pal, contexto, alvos, semente):
    def uma(alvo):
        return mod_gerador.encher(pasta / "cenas", pal, contexto, quantas=1, semente=semente, ecoar=print, alvos=[alvo])
    with ThreadPoolExecutor(max(1, len(alvos))) as pool:
        partes = list(pool.map(uma, alvos))
    return [laudo for parte in partes for laudo in parte]
def _gerar_e_montar(args, pasta, pal, contexto):
    alvos = [f.chave for f in gerar_banners._formatos_pedidos(getattr(args, "formatos", None)) if f in mod_formatos.COM_CENA]
    if not alvos or args.candidatas < 1 or args.so_fallback:
        return _gerar_e_montar_original(args, pasta, pal, contexto)
    inicio = time.time()
    try:
        laudos = _encher_paralelo(pasta, pal, contexto, alvos, 1)
    except mod_gerador.SemChave as erro:
        print(f"[ERRO] {erro}")
        return 2
    print(f"  cenas em paralelo: {sum(1 for l in laudos if l.get('ok'))}/{len(laudos)} em {time.time() - inicio:.0f}s")
    codigo = gerar_banners.montar(args)
    try:
        pecas = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8")).get("pecas") or {}
    except (OSError, ValueError):
        return codigo
    reprovados = [a for a in alvos if (pecas.get(a) or {}).get("origem") != "aprovado"]
    if codigo or not reprovados:
        return codigo
    if time.time() - inicio > 70:
        print(f"sem repescagem: {time.time() - inicio:.0f}s gastos")
        return codigo
    guardadas = pasta / "cenas-reprovadas"
    guardadas.mkdir(exist_ok=True)
    for arquivo in list((pasta / "cenas").iterdir()):
        if any(arquivo.stem.lower().startswith(a) for a in reprovados):
            shutil.move(str(arquivo), str(guardadas / f"{int(time.time() * 1000)}-{arquivo.name}"))
    print(f"REPESCAGEM {','.join(reprovados)}")
    _encher_paralelo(pasta, pal, contexto, reprovados, 101)
    args.formatos = ",".join(reprovados)
    return gerar_banners.montar(args)
gerar_banners._gerar_e_montar = _gerar_e_montar
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
    """Cores de identidade do site, guardadas em disco: a extração lê em paralelo com a
    busca e a geração do banner reaproveita sem baixar o site de novo."""
    import hashlib
    if not site or re.search(r"instagram\.com|facebook\.com|linktr\.ee", site):
        return []
    guardado = TRABALHO / "cores" / (hashlib.md5(("v2:" + site.strip().lower()).encode()).hexdigest() + ".json")
    try:
        return [tuple(c) for c in json.loads(guardado.read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        pass
    cores = _cores_do_site(site)
    if cores:
        guardado.parent.mkdir(parents=True, exist_ok=True)
        guardado.write_text(json.dumps(cores), encoding="utf-8")
    return cores


def _cores_do_site(site):
    """Cores de identidade do site: theme-color, variáveis CSS e cores mais usadas nos estilos."""
    import requests
    from urllib.parse import urljoin
    cab = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
    try:
        base = selecao.normalizar_site(site)
        pagina = requests.get(base, headers=cab, timeout=15).text
    except Exception:
        return []
    from urllib.parse import urlparse
    dominio = lambda u: ".".join((urlparse(u).hostname or "").lower().split(".")[-3:]).removeprefix("www.")
    proprio = dominio(base)
    textos = [pagina]
    folhas = [urljoin(base, h) for h in re.findall(r'<link[^>]+rel="?stylesheet"?[^>]+href="([^"]+)"', pagina)
              + re.findall(r'<link[^>]+href="([^"]+)"[^>]+rel="?stylesheet"?', pagina)]
    for url in [u for u in dict.fromkeys(folhas) if dominio(u) == proprio][:4]:
        try:
            textos.append(requests.get(url, headers=cab, timeout=10).text[:400000])
        except Exception:
            pass
    contagem = {}
    for m in re.findall(r'name="theme-color"\s+content="(#[0-9a-fA-F]{6})"', pagina):
        contagem[m.upper()] = contagem.get(m.upper(), 0) + 40
    for texto in textos:
        for m in re.findall(r"--[a-z-]*(?:primary|brand|marca|principal|main)[a-z-]*\s*:\s*(#[0-9a-fA-F]{6})\b", texto, re.I):
            contagem[m.upper()] = contagem.get(m.upper(), 0) + 60
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
    """(marca, apoio, origem): a cor da marca vem do site (é a que o cliente usa de fato);
    sem cor no site, vem da logo;
    a cor de apoio é a segunda cor do site (ou da logo), nunca um matiz inventado."""
    da_logo = cores_da_logo(logo) if logo else []
    do_site = cores_do_site(site)
    marca, apoio, origem = None, None, []
    if do_site:
        marca = do_site[0]
        origem.append("site")
        if da_logo and any(_dist_matiz(c, do_site[0]) <= 18 for c in da_logo):
            origem.append("logo")
    elif da_logo:
        marca = da_logo[0]
        origem.append("logo")
    candidatas = [c for c in do_site + da_logo if marca is None or _dist_matiz(c, marca) > 40]
    apoio = candidatas[0] if candidatas else None
    return (_hex(marca) if marca else None, _hex(apoio) if apoio else None, "+".join(origem) or "nenhuma")


def paleta_do_pedido(marca_hex, apoio_hex, gosto, anterior_hex=None, variar=False):
    """Cor principal (fundo) = cor da marca, a mesma regra de identidade_visual (logo + site,
    ou a cor que o usuário pediu). Só vira claro/escuro quando o usuário pede isso no refazer.
    Destaque = cor de apoio do site quando legível, senão branco/escuro legível. Nunca matiz inventado."""
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
        opcoes = na_marca[:1]
    anterior = anterior_hex.upper() if anterior_hex else None
    restantes = [o for o in opcoes if _hex(o[1]) != anterior] or opcoes
    nome, fundo = random.choice(restantes) if variar and gosto else restantes[0]
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


def gerar_pecas_paleta(caminho, logo, cliente, segmento, paleta, cena_ia=False, texto=""):
    """cena_ia=True (teste com os próximos pedidos): a IA desenha a cena ao lado do painel,
    com os produtos do catálogo e o pedido de mudança no prompt. Cena reprovada na régua
    cai no banner só com a marca, como antes."""
    import atendimento
    pasta = Path(caminho).parent
    embrulho = pasta / "embrulho_paleta.py"
    embrulho.write_text(EMBRULHO_PALETA, encoding="utf-8")
    dados = dict(paleta, _feedback=texto.strip()) if cena_ia and (texto or "").strip() else paleta
    if LAB_ATIVO:
        dados = dict(dados, _lab=True)
    comando = [sys.executable, str(embrulho), str(atendimento.GERADOR), json.dumps(dados), "auto",
               "--logo", str(logo), "--nome", cliente,
               "--segmento", segmento or atendimento.SEGMENTO_PADRAO,
               "--catalogo", str(caminho), "--regua-logo", "portal",
               "--cor", paleta["principal"]]
    comando += ["--candidatas", "1"] if cena_ia else ["--candidatas", "0", "--so-fallback"]
    if cena_ia:
        evento("banners", "cena do banner desenhada por IA: login e cabeçalho ao mesmo tempo, "
                          "segunda tentativa só para a peça reprovada")
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


PEDE_FOTOS = re.compile(r"salgad|produto|foto|imagem|comida|lanche|mostr|coxinha|pizza|doce|bebida", re.I)

EMBRULHO_MONTAR = r"""
import sys
from pathlib import Path
gerador = Path(sys.argv[1])
sys.path.insert(0, str(gerador.parent))
sys.argv = [str(gerador)] + sys.argv[2:]
import gerar_banners
import validar
validar.checar_cena = lambda *a, **k: []
__REMENDO_LOGO__
sys.exit(gerar_banners.main(sys.argv[1:]))
"""
EMBRULHO_MONTAR = EMBRULHO_MONTAR.replace("__REMENDO_LOGO__", EMBRULHO_PALETA[
    EMBRULHO_PALETA.index("import numpy as np"):EMBRULHO_PALETA.index("original = gerar_banners")])


def _baixar_foto(url):
    import requests
    from PIL import Image
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                   "AppleWebKit/537.36 Chrome/128 Safari/537.36"})
        if r.status_code != 200:
            return None
        img = Image.open(io.BytesIO(r.content))
        img.load()
        return img.convert("RGB")
    except Exception:
        return None


def _mosaico(fotos, largura, altura, colunas, linhas):
    from PIL import Image, ImageOps
    tela = Image.new("RGB", (largura, altura), (255, 255, 255))
    celulas = [(c, l) for l in range(linhas) for c in range(colunas)]
    for n, (c, l) in enumerate(celulas):
        foto = fotos[n % len(fotos)]
        x0, x1 = c * largura // colunas, (c + 1) * largura // colunas
        y0, y1 = l * altura // linhas, (l + 1) * altura // linhas
        tela.paste(ImageOps.fit(foto, (x1 - x0, y1 - y0), Image.LANCZOS), (x0, y0))
    return tela


def cenas_dos_produtos(caminho_catalogo, pasta_cenas):
    """Cena do banner feita com as FOTOS REAIS dos produtos do catálogo (mosaico).
    Devolve quantas fotos entraram; 0 = não deu para montar."""
    try:
        catalogo = json.loads(Path(caminho_catalogo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    urls = [p["imagem"] for p in _produtos_do_json(catalogo) if p.get("imagem")]
    with selecao.ThreadPoolExecutor(8) as pool:
        fotos = [f for f in pool.map(_baixar_foto, urls[:12]) if f is not None]
    boas = sorted(fotos, key=lambda f: -min(f.size))
    boas = [f for f in boas if min(f.size) >= 250] or boas
    if len(boas) < 2:
        return 0
    pasta_cenas.mkdir(parents=True, exist_ok=True)
    _mosaico(boas[:6], 1440, 1800, 2, 3).save(pasta_cenas / "login-produtos.jpg", quality=92)
    _mosaico(boas[:4], 1056, 320, 4, 1).save(pasta_cenas / "cabecalho-produtos.jpg", quality=92)
    return min(len(boas), 6)


def montar_com_fotos(pasta, caminho_catalogo):
    import atendimento
    import subprocess
    quantas = cenas_dos_produtos(caminho_catalogo, Path(pasta) / "cenas")
    if not quantas:
        evento("banners", "não consegui baixar fotos dos produtos; banners seguem só com a marca", "aviso")
        return False
    embrulho = Path(pasta) / "embrulho_montar.py"
    embrulho.write_text(EMBRULHO_MONTAR, encoding="utf-8")
    try:
        p = subprocess.run([sys.executable, str(embrulho), str(atendimento.GERADOR), "montar", str(pasta),
                            "--sem-juiz"], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        evento("banners", "montagem com fotos passou de 3 minutos; banners seguem só com a marca", "aviso")
        return False
    if p.returncode != 0:
        evento("banners", "montagem com fotos falhou: " + ((p.stdout or "") + (p.stderr or ""))[-300:], "aviso")
        return False
    evento("banners", f"banners montados com {quantas} fotos dos produtos do catálogo")
    return True


FRACAO_LOGO_VISIVEL = 0.45


def _visivel_no_fundo(logo, fundo_rgb):
    """Fração dos pixels da logo ORIGINAL que se destacam do fundo (contraste >= 2)."""
    from PIL import Image
    import numpy as np
    dados = np.asarray(Image.open(logo).convert("RGBA"), dtype=np.float64).reshape(-1, 4)
    opacos = dados[dados[:, 3] > 128][:, :3]
    if not len(opacos):
        return 1.0
    if len(opacos) > 20000:
        opacos = opacos[::len(opacos) // 20000]
    c = opacos / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    lum = 0.2126 * c[:, 0] + 0.7152 * c[:, 1] + 0.0722 * c[:, 2]
    lf = _lum(fundo_rgb)
    razao = (np.maximum(lum, lf) + 0.05) / (np.minimum(lum, lf) + 0.05)
    return float((razao >= 2.0).mean())


def _fundo_onde_a_logo_aparece(logo, marca_hex, nome, paleta):
    """Fundo na cor da marca só quando a logo original aparece nele. Se não aparece (logo
    vermelha em fundo vermelho), o gerador viraria a logo uma silhueta branca sem detalhes;
    aqui o banner passa para um fundo claro e a logo fica com as cores originais."""
    if not logo:
        return nome, paleta
    try:
        atual = _visivel_no_fundo(logo, _rgb(paleta["principal"]))
        if atual >= FRACAO_LOGO_VISIVEL:
            return nome, paleta
        marca = _rgb(marca_hex)
        opcoes = [("fundo claro na cor da marca", _misturar(marca, (255, 255, 255), 0.9)),
                  ("fundo branco", (255, 255, 255)),
                  ("fundo marca escura", _misturar(marca, (0, 0, 0), 0.6)),
                  ("fundo grafite", (28, 28, 30))]
        medidas = [(n, f, _visivel_no_fundo(logo, f)) for n, f in opcoes]
        escolhido = next((m for m in medidas if m[2] >= FRACAO_LOGO_VISIVEL), max(medidas, key=lambda m: m[2]))
        if escolhido[2] <= atual:
            return nome, paleta
        novo_nome, fundo, visivel = escolhido
        destaque = marca if _contraste(marca, fundo) >= 3 else _legivel_sobre(marca, fundo)
        neutra = (16, 20, 24) if _lum(fundo) > 0.4 else (247, 248, 250)
        evento("banners", f"a logo some no {nome} ({atual:.0%} visível): usando {novo_nome} "
                          f"{_hex(fundo)} ({visivel:.0%} visível), logo com as cores originais")
        return novo_nome, {"principal": _hex(fundo), "destaque": _hex(destaque), "neutra": _hex(neutra)}
    except Exception as erro:
        evento("banners", f"não deu para medir a logo no fundo: {type(erro).__name__}", "aviso")
        return nome, paleta


INSTRUCAO_CONFERIR_PECAS = """Você confere os banners de um portal B2B da empresa "{cliente}" antes de irem ao ar.
A primeira imagem é a logo correta da empresa; depois vêm as peças numeradas.
Para cada peça, reprove (ok=false) se: a logo da empresa não aparece, aparece como retângulo ou
bloco de cor chapada, borrão ou silhueta irreconhecível; há caixa vazia, placeholder ou imagem quebrada;
texto cortado, sobreposto ou ilegível sobre o fundo. Fundo simples sem foto é aceitável.
Responda só JSON: {{"pecas": [{{"n": 0, "ok": true, "motivo": ""}}]}}"""


def conferir_pecas_ia(pasta, logo, cliente):
    """Lista de motivos das peças reprovadas ([] = todas aprovadas ou IA indisponível)."""
    import subir_banners
    pecas, _ = subir_banners.pecas_da_pasta(pasta)
    chaves = sorted(pecas)
    imagens = [("Logo correta da empresa:", _jpeg_sobre(logo, (255, 255, 255)))]
    imagens += [(f"Peça {n} ({chave}):", _jpeg_sobre(pecas[chave], (255, 255, 255), 1024))
                for n, chave in enumerate(chaves)]
    resposta, ia = _ia_visao(INSTRUCAO_CONFERIR_PECAS.format(cliente=cliente or "cliente"), imagens)
    if resposta is None:
        evento("banners", f"conferência visual dos banners indisponível ({ia})", "aviso")
        return []
    reprovadas = [f"{chaves[int(p['n'])]}: {p.get('motivo') or 'reprovada'}" for p in resposta.get("pecas") or []
                  if p.get("ok") is False and str(p.get("n")).isdigit() and int(p["n"]) < len(chaves)]
    evento("banners", f"conferência visual dos banners ({ia}): "
                      + ("todas aprovadas" if not reprovadas else "REPROVADAS " + "; ".join(reprovadas)),
           "aviso" if reprovadas else "info")
    return reprovadas


def gerar_com_identidade(entrada, caminho, logo, variar=False, anterior=None, texto=""):
    """Peças base conferidas; fora do laboratório, login e cabeçalho viram o banner do zero guiado
    (se a Images API falhar ou reprovar, ficam as peças base)."""
    nova, saida, paleta = _gerar_base_conferida(entrada, caminho, logo, variar, anterior, texto)
    if nova and logo and not LAB_ATIVO:
        try:
            import subir_banners
            pecas, _ = subir_banners.pecas_da_pasta(nova)
            if not _lab_do_zero(pecas, logo, entrada, paleta, minimo=True, pedido=(texto or "").strip()[:300]):
                evento("banners", "banner do zero não saiu; ficaram as peças padrão", "aviso")
        except Exception as erro:
            evento("banners", f"banner do zero falhou ({type(erro).__name__}: {str(erro)[:160]}); ficaram as peças padrão", "aviso")
    if nova and not LAB_ATIVO:
        _mobile_seguro(nova, logo, entrada.get("cliente") or "")
    return nova, saida, paleta


def _gerar_base_conferida(entrada, caminho, logo, variar=False, anterior=None, texto=""):
    """Gera e confere as peças. Reprovada na conferência visual: refaz uma vez com fundo claro
    da marca e a logo nas cores originais; reprovada de novo, não sai banner (nunca vai ao ar)."""
    nova, saida, paleta = _gerar_com_identidade(entrada, caminho, logo, variar, anterior, texto)
    if not nova or not logo:
        return nova, saida, paleta
    try:
        reprovadas = conferir_pecas_ia(nova, logo, entrada.get("cliente"))
    except Exception as erro:
        evento("banners", f"conferência visual dos banners falhou ({type(erro).__name__}: {erro})", "aviso")
        reprovadas = []
    if not reprovadas:
        return nova, saida, paleta
    marca = _rgb(paleta.get("destaque") or paleta["principal"])
    fundo = _misturar(marca, (255, 255, 255), 0.9)
    clara = {"principal": _hex(fundo), "destaque": _hex(marca if _contraste(marca, fundo) >= 3 else _legivel_sobre(marca, fundo)),
             "neutra": "#101418"}
    evento("banners", f"refazendo os banners com fundo claro {clara['principal']} e a logo nas cores originais")
    nova, saida = gerar_pecas_paleta(caminho, logo, entrada.get("cliente") or "", entrada.get("segmento"), clara)
    if nova and not conferir_pecas_ia(nova, logo, entrada.get("cliente")):
        return nova, saida, clara
    motivo = "banners reprovados na conferência visual: " + "; ".join(reprovadas)
    evento("banners", motivo + " · os banners não vão para o portal", "erro")
    return None, motivo, paleta


def _gerar_com_identidade(entrada, caminho, logo, variar=False, anterior=None, texto=""):
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
    nome, paleta = paleta_do_pedido(marca, apoio, gosto, anterior, variar)
    if not gosto:
        nome, paleta = _fundo_onde_a_logo_aparece(logo, marca, nome, paleta)
    evento("banners", f"identidade: marca {marca}" + (f", apoio {apoio}" if apoio else "") + f" (de {origem}); "
                      f"{nome} {paleta['principal']}, destaque {paleta['destaque']}"
                      + (f"; gosto {gosto} ({fonte_gosto})" if gosto else ""))
    cena_ia = bool(entrada.get("cena_ia"))
    nova, saida = gerar_pecas_paleta(caminho, logo, entrada.get("cliente") or "", entrada.get("segmento"), paleta,
                                     cena_ia=cena_ia, texto=texto)
    if nova and cena_ia:
        try:
            manifesto = json.loads((Path(nova) / "manifesto.json").read_text(encoding="utf-8"))
            origens = {k: v.get("origem") for k, v in (manifesto.get("pecas") or {}).items()
                       if k in ("login", "cabecalho")}
            evento("banners", "cena por IA: " + ", ".join(
                f"{k} {'aprovada' if o == 'aprovado' else 'reprovada, ficou só a marca'}" for k, o in origens.items()))
        except (OSError, ValueError):
            pass
    if nova and texto and PEDE_FOTOS.search(texto) and not cena_ia:
        montar_com_fotos(nova, caminho)
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
    evento("banners", "gerando as peças (login, cabeçalho web e mobile)")
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


def url_pelo_portal_id(portal_id):
    """Endereço do portal lido na própria Zydon (login com solution_id + /api/b2b/portals/info).
    Só vale se a página abrir: 2xx no info não prova nada."""
    import requests
    import credenciais
    try:
        headers, _ = credenciais.carregar(ORG)
        login = requests.post(f"{credenciais.ACCOUNT_BASE_URL}/access-key/login", timeout=20,
                              json={"code": headers["X-Zydon-Access-Key-Code"],
                                    "token": headers["X-Zydon-Access-Key-Token"], "solution_id": portal_id})
        token = (login.json() or {}).get("accessToken") if login.status_code == 200 else None
        if not token:
            return None
        info = requests.get("https://api.zydon.com.br/api/b2b/portals/info", timeout=20,
                            headers={"Authorization": "Bearer " + token})
        url = ((info.json() or {}).get("url") or "").strip() if info.status_code == 200 else ""
        if not url:
            return None
        if not url.startswith("http"):
            url = "https://" + url
        pagina = requests.get(url, timeout=25)
        return url if pagina.status_code < 400 else None
    except Exception as erro:
        evento("criacao", f"não deu para ler o endereço pelo id do portal: {type(erro).__name__}", "aviso")
        return None


def criar(entrada):
    import atendimento
    pedido_id = entrada["pedido_id"]
    pasta = pasta_pedido(pedido_id)
    logo = restaurar_logo(entrada, pasta)
    banners = restaurar_banners(entrada, pasta)
    renovar_imagens_do_anexo(entrada["catalogo"])
    if entrada.get("automatico"):
        if isinstance(entrada["catalogo"], str):
            entrada["catalogo"] = json.loads(entrada["catalogo"])
        nome_cliente = " ".join(str(entrada.get("cliente") or entrada["catalogo"].get("empresa") or "").split())
        entrada["catalogo"]["portal_name"] = f"poc-{nome_cliente}"
        evento("criacao", f"portal do Dexter: nome {entrada['catalogo']['portal_name']}")
    caminho = gravar_catalogo(entrada["catalogo"], pedido_id)
    simular = bool(entrada.get("simular"))
    evento("criacao", "simulação: valida sem criar nada" if simular else "criando o portal na org pocs")
    resultado = atendimento.atender(caminho, logo, ORG, True, pedido_id=pedido_id,
                                    origem_id=pedido_id, simular=simular)
    if not simular and resultado.get("portal_id"):
        url = url_pelo_portal_id(resultado["portal_id"])
        if url and url.rstrip("/") != (resultado.get("url") or "").rstrip("/"):
            evento("criacao", f"endereço lido pelo id do portal (o nome pode repetir outro portal): {url}")
            resultado = dict(resultado, status="concluido", url=url,
                             observacoes=resultado.get("observacoes") if resultado.get("status") == "concluido" else "")
    saida = {"resultado": resultado}
    if resultado.get("status") == "concluido" and banners:
        _mobile_seguro(banners, logo, entrada.get("cliente") or "", so_se_faltar=True)
        try:
            evento("banners", "publicando as peças no portal (ainda não aplicadas)")
            saida["publicadas"] = atendimento.publicar_pecas(ORG, resultado["portal_id"], banners)
        except Exception as erro:
            saida["publicar_erro"] = f"{type(erro).__name__}: {erro}"
    if resultado.get("status") == "concluido" and resultado.get("portal_id"):
        try:
            catalogo = entrada["catalogo"] if isinstance(entrada["catalogo"], dict) else json.loads(entrada["catalogo"])
            saida["telufia"] = ativar_telufia(catalogo, entrada.get("cliente") or "", entrada.get("segmento") or "",
                                              resultado["portal_id"])
        except Exception as erro:
            saida["telufia"] = {"situacao": "falhou", "motivo": f"{type(erro).__name__}: {erro}"[:300]}
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
        if nova:
            _mobile_seguro(nova, None, entrada.get("cliente") or "")
    else:
        raise RuntimeError(f"ação de banner desconhecida: {acao}")
    if not nova:
        raise RuntimeError(str(saida)[-800:])
    if "cabecalho" in pecas and MOBILE not in pecas:
        pecas = list(pecas) + [MOBILE]
    resposta = {"pecas": pecas_para_tela(nova, set(pecas)), "cor": cor_da_pasta(nova),
                "banners_tar": empacotar(nova)}
    if portal_id:
        resposta["publicadas"] = atendimento.publicar_pecas(ORG, portal_id, nova, set(pecas))
    return resposta



ZOE_URL = "https://api.zydon.com.br/api/ai/zoe/configurations"
FERRAMENTAS_ZOE = (
    "- Para dados atualizados, use: [Ver detalhes do produto](TOOL:get_product_details), [Buscar produtos](TOOL:search_products), "
    "[Encontrar variações de um produto](TOOL:find_product_variations), [Buscar produtos similares](TOOL:get_similar_products), "
    "[Buscar produtos recomendados](TOOL:get_recommended_products), [Ver descontos por quantidade do produto](TOOL:get_quantity_discounts), "
    "[Listar categorias](TOOL:list_categories).\n"
    "- Para montar o pedido, use: [Adicionar itens ao carrinho](TOOL:add_cart_item), [Ver carrinho](TOOL:get_cart), "
    "[Finalizar compra](TOOL:create_order).")

INSTRUCAO_TELUFIA = """Você escreve a consultoria comercial da Telufia, assistente de vendas B2B da empresa "{cliente}" (segmento: {segmento}).
Use SÓ o que está nos nomes e descrições abaixo. Não invente característica técnica, sabor, cor, embalagem nem preço.
Devolva:
- "descricao_empresa": 1 frase sobre o que a empresa vende e para quem (sem inventar marcas).
- "criterios": critérios de compra do segmento em poucas palavras (ex.: giro, margem, formato).
- "perguntas": 2 ou 3 perguntas curtas que definem a recomendação nesse segmento.
- "frase_personalidade": 1 frase sobre o que a Telufia faz pelo cliente.
- "fichas": para cada produto (pelo número n), 2 a 3 frases curtas: uso, para quem, argumento de venda e um combo com outro produto DA LISTA (cite pelo nome).
Responda só JSON: {{"descricao_empresa": "...", "criterios": "...", "perguntas": ["..."], "frase_personalidade": "...", "fichas": [{{"n": 0, "texto": "..."}}]}}

Produtos:
{lista}"""


def _reais(valor):
    if valor in (None, "", 0):
        return "Preço indisponível"
    return "R$ " + f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def prompt_telufia(catalogo, cliente, segmento):
    """(personalidade, prompt, custo). Dados de produto vêm do JSON da POC; a IA só escreve a consultoria."""
    etapas = {e.get("endpoint"): e for e in catalogo.get("etapas") or []}
    categorias = {f"{{{{{r.get('salvar_id_como')}}}}}": r["payload"]["name"]
                  for r in (etapas.get("categories") or {}).get("requests") or []}
    produtos = [r["payload"] for r in (etapas.get("products") or {}).get("requests") or []]
    lista = "\n".join(f"{n}. {p['name']} | categoria: {categorias.get(p.get('category_id'), '-')} | {(p.get('description') or '')[:200]}"
                      for n, p in enumerate(produtos))
    dados, custo = {}, {}
    try:
        dados, custo = selecao._chamar_openrouter([{"role": "user", "content": INSTRUCAO_TELUFIA.format(
            cliente=cliente, segmento=segmento or "comércio B2B", lista=lista)}])
    except Exception as erro:
        evento("telufia", f"IA não escreveu a consultoria ({type(erro).__name__}); usando as descrições do catálogo", "aviso")
    fichas = {int(f.get("n")): selecao.limpar_texto(f.get("texto")) for f in dados.get("fichas") or []
              if str(f.get("n", "")).isdigit() and f.get("texto")}
    perguntas = [selecao.limpar_texto(x) for x in dados.get("perguntas") or [] if x][:3] \
        or ["qual o tipo do seu negócio", "qual volume você costuma comprar"]
    blocos = {}
    for n, p in enumerate(produtos):
        cat = categorias.get(p.get("category_id"), "Produtos")
        ficha = fichas.get(n) or selecao.limpar_texto(p.get("description") or "")[:240]
        linha = f"- {p['name']} ({p.get('sku')}) · {_reais(p.get('price'))} · mín. {p.get('minimum_for_sale') or 1}. {ficha}".strip()
        grade = p.get("variations") or []
        if grade:
            eixo = (grade[0].get("values") or [{}])[0].get("name") or "Variação"
            valores = ", ".join(v["values"][0]["value"] for v in grade if v.get("values"))
            linha += f" {eixo}: {valores}."
        blocos.setdefault(cat, []).append(linha)
    catalogo_txt = "\n\n".join(f"{cat.upper()}\n" + "\n".join(linhas) for cat, linhas in blocos.items())
    descricao = selecao.limpar_texto(dados.get("descricao_empresa")) or f"A {cliente} atende clientes B2B em {segmento or 'seu segmento'}."
    criterios = selecao.limpar_texto(dados.get("criterios")) or "giro, margem e mix"
    personalidade = (f"Oi, sou a Telufia, consultora comercial da {cliente}. "
                     + (selecao.limpar_texto(dados.get("frase_personalidade")) or "Ajudo você a montar o pedido certo para o seu negócio."))
    prompt = (f"Você é a Telufia, consultora comercial da {cliente}. {descricao}\n\n"
              f"Objetivo: ajudar o cliente a montar o pedido certo ({criterios}). Antes de recomendar, pergunte "
              + "; ".join(perguntas) + ".\n\n"
              "Catálogo de referência (valores da POC; confirme preço e estoque atuais pelas ferramentas, nunca use estes valores como final):\n\n"
              f"{catalogo_txt}\n\n"
              "Regras:\n"
              "- Recomende só itens deste catálogo. Nunca invente preço, estoque, sabor, cor ou embalagem.\n"
              "- Se o preço vier nulo ou o item estiver indisponível, diga \"Preço indisponível\", nunca \"R$ 0,00\". Sem estoque, diga \"Estoque indisponível\".\n"
              f"{FERRAMENTAS_ZOE}\n"
              "- O catálogo acima serve para a consultoria (uso, público, combo). Preço e estoque final vêm sempre das ferramentas.\n"
              "- Respostas curtas e consultivas. Termine sempre com um próximo passo ou um combo sugerido.")
    return personalidade, prompt, custo


def ativar_telufia(catalogo, cliente, segmento, portal_id):
    """Grava a Zoe como Telufia no portal (login com solution_id = portal) e confere por GET.
    2xx não prova nada: só vale se o GET devolver assistant_name = Telufia."""
    import requests
    import credenciais
    headers, _ = credenciais.carregar(ORG)
    login = requests.post(f"{credenciais.ACCOUNT_BASE_URL}/access-key/login", timeout=20,
                          json={"code": headers["X-Zydon-Access-Key-Code"], "token": headers["X-Zydon-Access-Key-Token"],
                                "solution_id": portal_id})
    if login.status_code != 200 or not (login.json() or {}).get("accessToken"):
        return {"situacao": "falhou", "motivo": f"login no portal respondeu HTTP {login.status_code}"}
    bearer = {"Authorization": "Bearer " + login.json()["accessToken"], "Content-Type": "application/json"}
    personalidade, prompt, custo = prompt_telufia(catalogo, cliente, segmento)
    evento("telufia", f"ativando a Telufia no portal (prompt com {len(prompt)} caracteres)")
    gravacao = requests.put(ZOE_URL, headers=bearer, timeout=30,
                            json={"assistant_name": "Telufia", "assistant_personality": personalidade, "assistant_prompt": prompt})
    if gravacao.status_code >= 300:
        return {"situacao": "falhou", "motivo": f"PUT da Zoe respondeu HTTP {gravacao.status_code}: {gravacao.text[:200]}"}
    conferencia = requests.get(ZOE_URL, headers=bearer, timeout=20)
    lido = conferencia.json() if conferencia.status_code == 200 and conferencia.text.strip() else {}
    if (lido or {}).get("assistant_name") != "Telufia":
        return {"situacao": "falhou", "motivo": f"GET da Zoe não confirmou a Telufia (HTTP {conferencia.status_code})"}
    evento("telufia", "Telufia ativada e conferida no portal")
    return {"situacao": "ativada", "caracteres": len(prompt), "custo": custo}


def telufia(entrada):
    catalogo = entrada["catalogo"]
    if isinstance(catalogo, str):
        catalogo = json.loads(catalogo)
    return {"telufia": ativar_telufia(catalogo, entrada["cliente"], entrada.get("segmento") or "", entrada["portal_id"])}

def url_portal(entrada):
    return {"url": url_pelo_portal_id(entrada["portal_id"])}


CAMPOS_APARENCIA = ("title", "billing_name", "fiscal_registration_number", "color", "brand_image",
                    "favicon_image", "login_image", "extend_screen", "menu_guidance", "display_watermark",
                    "floating_button", "tag_manager", "use_main_seller_phone_as_whatsapp_number", "is_open_to_public")


def loja_publica(entrada):
    """Liga/desliga "Loja visível para visitantes" (is_open_to_public) e confere por GET.
    O PUT substitui a aparência inteira: manda todos os campos lidos, só troca o flag."""
    import time
    import requests
    import credenciais
    portal_id, publico = entrada["portal_id"], bool(entrada.get("publico"))
    headers, _ = credenciais.carregar(ORG)
    token = None
    for tentativa in range(3):
        login = requests.post(f"{credenciais.ACCOUNT_BASE_URL}/access-key/login", timeout=30,
                              json={"code": headers["X-Zydon-Access-Key-Code"],
                                    "token": headers["X-Zydon-Access-Key-Token"], "solution_id": portal_id})
        if login.status_code == 200:
            token = (login.json() or {}).get("accessToken")
            break
        if login.status_code < 500:
            break
        time.sleep(3)
    if not token:
        return {"situacao": "falhou", "motivo": f"login no portal respondeu HTTP {login.status_code}"}
    bearer = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    url = "https://api.zydon.com.br/api/b2b/portals/appearance"
    atual = requests.get(url, headers=bearer, timeout=30)
    if atual.status_code != 200:
        return {"situacao": "falhou", "motivo": f"GET da aparência respondeu HTTP {atual.status_code}"}
    antes = atual.json()
    corpo = {k: antes[k] for k in CAMPOS_APARENCIA if k in antes}
    corpo["is_open_to_public"] = publico
    gravacao = requests.put(url, headers=bearer, json=corpo, timeout=30)
    if gravacao.status_code >= 300:
        return {"situacao": "falhou", "motivo": f"PUT da aparência respondeu HTTP {gravacao.status_code}: {gravacao.text[:200]}"}
    depois = requests.get(url, headers=bearer, timeout=30).json()
    mudou = [k for k in CAMPOS_APARENCIA if k != "is_open_to_public" and antes.get(k) != depois.get(k)]
    ok = depois.get("is_open_to_public") is publico
    evento("portal", f"loja visível para visitantes: {antes.get('is_open_to_public')} -> {depois.get('is_open_to_public')}"
           + (f" · outros campos mudaram: {', '.join(mudou)}" if mudou else ""), "info" if ok and not mudou else "aviso")
    return {"situacao": "ok" if ok else "nao_confirmado", "antes": antes.get("is_open_to_public"),
            "depois": depois.get("is_open_to_public"), "outros_campos_mudaram": mudou}



# --- Laboratorio de banners: canto direito composto com as fotos reais dos produtos ---
# Rodada 2: sem bolas nem pontos; divisor em arco na cor da marca, fundo contínuo com o
# painel, produto com o fundo trocado pela cor do painel (Images API) e recortado por ela.
MODELOS_LAB = ("diagonal", "vitrine", "em_uso", "padrao_marca", "trio", "destaque")
INICIO_LIVRE = {"login": 0.58, "cabecalho": 0.50}
PINTAR_DE = {"login": 0.58, "cabecalho": 0.45}
LAB_ATIVO = False
IMAGES_URL = ("https://dhsseifv2j3ti.cloudfront.net/legacy/public/serverFunction/"
              "b0320b4b-8957-4ce4-ad7d-afa12c6c87df/2b57e9c5-cf8e-4686-ab1a-a86b9e8eeaa8/execute")
PALETA_WORDPRESS = {"#000000", "#FFFFFF", "#ABB8C3", "#F78DA7", "#CF2E2E", "#FF6900", "#FCB900", "#7BDCB5",
                    "#00D084", "#8ED1FC", "#0693E3", "#9B51E0", "#EEEEEE", "#313131", "#32373C",
                    "#9B59B6", "#3498DB", "#2ECC71", "#E74C3C", "#F1C40F", "#1ABC9C", "#E67E22", "#34495E"}
CDN_DE_BIBLIOTECA = re.compile(r"fonts\.googleapis|fontawesome|bootstrapcdn|jsdelivr\.net/npm/(bootstrap|swiper|slick)"
                               r"|cdnjs\.cloudflare\.com|unpkg\.com|wp-includes|wp-block-library", re.I)


def _cores_do_site_lab(site):
    """Como _cores_do_site, mas lê também as folhas do CDN do próprio site (não as de
    bibliotecas) e ignora a paleta padrão do WordPress/Gutenberg e de temas prontos."""
    import requests
    from urllib.parse import urljoin
    cab = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
    try:
        base = selecao.normalizar_site(site)
        pagina = requests.get(base, headers=cab, timeout=15).text
    except Exception:
        return []
    textos = [pagina]
    folhas = [urljoin(base, h) for h in re.findall(r'<link[^>]+rel="?stylesheet"?[^>]+href="([^"]+)"', pagina)
              + re.findall(r'<link[^>]+href="([^"]+)"[^>]+rel="?stylesheet"?', pagina)]
    for url in [u for u in dict.fromkeys(folhas) if not CDN_DE_BIBLIOTECA.search(u)][:6]:
        try:
            textos.append(requests.get(url, headers=cab, timeout=10).text[:400000])
        except Exception:
            pass
    limpos = [re.sub(r"--wp--preset--[a-z0-9-]+\s*:[^;}]+[;}]", "", t, flags=re.I) for t in textos]
    contagem = {}
    for m in re.findall(r'name="theme-color"\s+content="(#[0-9a-fA-F]{6})"', pagina):
        contagem[m.upper()] = contagem.get(m.upper(), 0) + 40
    for texto in limpos:
        for m in re.findall(r"--[a-z-]*(?:primary|brand|marca|principal|main)[a-z-]*\s*:\s*(#[0-9a-fA-F]{6})\b", texto, re.I):
            contagem[m.upper()] = contagem.get(m.upper(), 0) + 60
        for m in re.findall(r"#([0-9a-fA-F]{6})\b", texto):
            contagem["#" + m.upper()] = contagem.get("#" + m.upper(), 0) + 1
    saida = []
    for hexa, _ in sorted(contagem.items(), key=lambda kv: -kv[1]):
        if hexa in PALETA_WORDPRESS:
            continue
        rgb = _rgb(hexa)
        if _saturacao(rgb) < 0.4 or max(rgb) < 60:
            continue
        if all(_dist_matiz(rgb, o) > 20 for o in saida):
            saida.append(rgb)
        if len(saida) >= 4:
            break
    return saida


def _identidade_lab(site, logo, navegador=None):
    """Cor do lab: a do navegador (site renderizado) vale mais; sem ela, a do site só vale se
    conversar com a logo; site fraco ou sem cor cai na cor da logo."""
    da_logo = cores_da_logo(logo) if logo else []
    do_site = [ _rgb(c) for c in (navegador or []) if isinstance(c, str) and c.startswith("#")]
    origem = "navegador"
    if not do_site:
        do_site, origem = _cores_do_site_lab(site) if site else [], "site"
    marca = None
    if do_site and da_logo:
        casadas = [c for c in do_site if any(_dist_matiz(c, l) <= 18 for l in da_logo)]
        if casadas:
            marca, origem = casadas[0], origem + "+logo"
        elif origem == "navegador":
            marca = do_site[0]
        else:
            marca, origem = da_logo[0], "logo (site fraco)"
    elif do_site:
        marca = do_site[0]
    elif da_logo:
        marca, origem = da_logo[0], "logo"
    if marca is None:
        return None, None, "nenhuma"
    candidatas = [c for c in do_site + da_logo if _dist_matiz(c, marca) > 40]
    apoio = candidatas[0] if candidatas else None
    return _hex(marca), (_hex(apoio) if apoio else None), origem


def _images_api(nome, argumentos):
    import requests
    chave = os.environ.get("IMAGES_API_KEY")
    if not chave:
        return None
    corpo = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": nome, "arguments": argumentos}}
    r = requests.post(IMAGES_URL, json=corpo, headers={"x-api-key": chave}, timeout=150)
    saida = (r.json().get("result") or {}).get("output") or {}
    if isinstance(saida, str):
        saida = json.loads(saida)
    res = saida.get("result") if isinstance(saida, dict) else None
    if isinstance(res, str):
        res = json.loads(res)
    return res or None


def _editar_imagem(foto, prompt, espera=300, lado=1024):
    """Edita a foto pela Images API (sempre devolve JPEG). None quando falha ou demora."""
    import time
    from PIL import Image
    try:
        img = foto.convert("RGB")
        img.thumbnail((lado, lado), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        for tentativa in range(4):
            if tentativa:
                time.sleep(15 * tentativa + random.uniform(0, 10))
            res = _images_api("editar_imagem", {"prompt": prompt, "imagem": uri, "formato": "jpeg"})
            inicio = time.time()
            while res:
                sc = res.get("structuredContent") or {}
                dado = next((c.get("data") for c in res.get("content") or [] if c.get("type") == "image" and c.get("data")), None)
                if dado:
                    return Image.open(io.BytesIO(base64.b64decode(dado))).convert("RGB")
                if sc.get("status") == "processando" and sc.get("id") and time.time() - inicio <= espera:
                    time.sleep(max(6, min(20, float(sc.get("retryAfterSeconds") or 10))))
                    res = _images_api("consultar_imagem", {"id": sc["id"]})
                    continue
                break
            if res and (res.get("structuredContent") or {}).get("status") == "processando":
                evento("banners", "API de imagem demorou demais; desisti desta peça", "aviso")
                return None
            texto = " ".join(c.get("text", "") for c in (res or {}).get("content") or [] if c.get("type") == "text")
            evento("banners", f"API de imagem não devolveu a imagem (tentativa {tentativa + 1} de 4): {texto[:200] or 'sem resposta'}", "aviso")
    except Exception as erro:
        evento("banners", f"API de imagem falhou ({str(erro)[:160]})", "aviso")
    return None


def _recortar_produto(foto):
    """Tira o fundo liso (branco/cinza) ligado às bordas. Devolve (RGBA, recortou)."""
    from PIL import Image, ImageDraw, ImageFilter
    img = foto.convert("RGB")
    lado = 900
    if max(img.size) > lado:
        img.thumbnail((lado, lado), Image.LANCZOS)
    marcada = img.copy()
    sentinela = (1, 254, 3)
    w, h = marcada.size
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        canto = marcada.getpixel(xy)
        if canto != sentinela and min(canto) > 200 and max(canto) - min(canto) < 30:
            ImageDraw.floodfill(marcada, xy, sentinela, thresh=28)
    dados = marcada.getdata()
    alfa = Image.new("L", marcada.size)
    alfa.putdata([0 if px == sentinela else 255 for px in dados])
    fora = 1 - sum(alfa.histogram()[128:]) / float(w * h)
    if fora < 0.06 or fora > 0.92:
        return img.convert("RGBA"), False
    alfa = alfa.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    rgba = img.convert("RGBA")
    rgba.putalpha(alfa)
    caixa = alfa.point(lambda v: 255 if v > 40 else 0).getbbox()
    return (rgba.crop(caixa) if caixa else rgba), True


def _recortar_pela_cor(img):
    """A foto voltou da Images API com fundo liso de cor conhecida: tudo que é dessa cor e
    toca a borda vira transparente, e também os vãos internos quase idênticos a ela."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    rgb = img.convert("RGB")
    w, h = rgb.size
    arr = np.asarray(rgb, dtype=np.int16)
    bordas = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    chave = np.median(bordas, axis=0)
    dist = np.abs(arr - chave).sum(axis=2)
    marcada = Image.fromarray(np.where(dist < 54, 255, 0).astype("uint8"))
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)):
        if marcada.getpixel(xy) == 255:
            ImageDraw.floodfill(marcada, xy, 128)
    m = np.asarray(marcada)
    fora = (m == 128) | (dist < 20)
    alfa = Image.fromarray(np.where(fora, 0, 255).astype("uint8"))
    frac = float(fora.mean())
    if frac < 0.08 or frac > 0.93:
        return None
    alfa = alfa.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.4))
    saida = rgb.convert("RGBA")
    saida.putalpha(alfa)
    caixa = alfa.point(lambda v: 255 if v > 40 else 0).getbbox()
    return saida.crop(caixa) if caixa else saida


def _qualidade(foto):
    """Nota da foto como candidata: grande, fundo liso recortável, produto ocupando bem."""
    if min(foto.size) < 300:
        return -1, None
    recorte, ok = _recortar_produto(foto)
    if not ok:
        return 0.5, None
    ocupa = (recorte.size[0] * recorte.size[1]) / float(min(foto.size[0], 900) * min(foto.size[1], 900) or 1)
    if ocupa < 0.08:
        return 0.2, recorte
    return 1 + min(1.0, min(foto.size) / 800.0) + min(0.6, ocupa), recorte


def _fotos_lab(catalogo, quantas, fundo_hex):
    """Escolhe as melhores fotos do catálogo e troca o fundo pela cor do painel (Images API),
    recortando pela cor conhecida. Sem API, cai no recorte por fundo branco."""
    urls = [p["imagem"] for p in _produtos_do_json(catalogo) if p.get("imagem")]
    with selecao.ThreadPoolExecutor(4) as pool:
        fotos = [f for f in pool.map(_baixar_foto, urls[:12]) if f is not None]
    avaliadas = sorted(((_qualidade(f), f) for f in fotos), key=lambda t: -t[0][0])
    boas = [(f, r) for (nota, r), f in avaliadas if nota >= 1][:quantas]
    if not boas:
        return [], []
    prompt = (f"Fotografia publicitária de estúdio. Mantenha o produto exatamente igual: forma, cores, logotipos, "
              f"rótulos e peças. Substitua todo o fundo por um fundo liso e uniforme na cor exata {fundo_hex}, "
              f"sem textura, sem gradiente, sem objetos, sem texto, sem sombra no fundo. Inclua os vãos internos do produto.")
    with selecao.ThreadPoolExecutor(len(boas)) as pool:
        editadas = list(pool.map(lambda par: _editar_imagem(par[0], prompt), boas))
    saida = []
    for (foto, recorte), editada in zip(boas, editadas):
        limpa = _recortar_pela_cor(editada) if editada is not None else None
        saida.append(limpa or recorte)
    evento("banners", f"laboratório: {len(saida)} fotos escolhidas de {len(fotos)}; "
                      f"{sum(1 for e in editadas if e is not None)} com fundo trocado pela Images API")
    return saida, [f for f, _ in boas]


def _produto_em_uso(foto, fundo_hex, segmento):
    prompt = (f"Fotografia publicitária realista do mesmo produto em uso, num ambiente coerente com o segmento "
              f"{segmento or 'do cliente'}. Mantenha o produto idêntico (forma, cores, rótulos). Luz natural, "
              f"composição limpa, sem pessoas com rosto visível, sem texto, sem logotipos novos. "
              f"Tons do ambiente que combinem com a cor {fundo_hex}.")
    return _editar_imagem(foto, prompt)


def _colar_com_sombra(tela, img, cx, base_y, altura, limite_largura=0.46, chao=True):
    """Cola o produto com a base em base_y e uma sombra de contato discreta."""
    from PIL import Image, ImageDraw, ImageFilter
    fator = altura / img.size[1]
    largura = max(1, int(img.size[0] * fator))
    limite = int(tela.size[0] * limite_largura)
    if largura > limite:
        fator = limite / img.size[0]
        largura, altura = limite, max(1, int(img.size[1] * fator))
    prod = img.resize((largura, int(altura)), Image.LANCZOS)
    x, y = int(cx - largura / 2), int(base_y - altura)
    if chao:
        camada = Image.new("RGBA", tela.size, (0, 0, 0, 0))
        rx, ry = largura * 0.40, max(5, altura * 0.025)
        ImageDraw.Draw(camada).ellipse([cx - rx, base_y - ry, cx + rx, base_y + ry], fill=(0, 0, 0, 70))
        tela.alpha_composite(camada.filter(ImageFilter.GaussianBlur(max(4, altura * 0.025))))
    sombra = Image.new("RGBA", tela.size, (0, 0, 0, 0))
    sombra.paste(Image.new("RGBA", prod.size, (0, 0, 0, 45)), (x + int(altura * 0.02), y + int(altura * 0.025)), prod.getchannel("A"))
    tela.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(max(6, altura * 0.035))))
    tela.alpha_composite(prod, (x, y))
    return x, y, largura, int(altura)


def _misturar_rgb(a, b, peso):
    return tuple(int(a[i] * (1 - peso) + b[i] * peso) for i in range(3))


def _tons_lab(fundo, destaque):
    escuro = _lum(fundo) < 0.08
    claro = _lum(fundo) > 0.6
    arco = _misturar_rgb(fundo, (255, 255, 255), 0.10) if escuro else _misturar_rgb(fundo, (0, 0, 0), 0.10 if claro else 0.20)
    linha = destaque if _contraste(destaque, arco) >= 1.8 else _misturar_rgb(arco, (255, 255, 255) if not claro else (0, 0, 0), 0.35)
    sutil = _misturar_rgb(fundo, (0, 0, 0) if claro else (255, 255, 255), 0.06)
    return arco, linha, sutil


def _arco(regiao, chave, cor, linha, deslocar=0.0):
    """Divisor em arco (referência Voolt3D/Panattos): um grande arco entra pela direita na
    cor da marca mais funda, com um fio fino de destaque acompanhando a curva."""
    from PIL import Image, ImageDraw
    rw, rh = regiao.size
    camada = Image.new("RGBA", regiao.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    if chave == "login":
        r = rh * 0.78
        cx, cy = rw * (1.02 + deslocar) + r * 0.30, rh * 0.62
    else:
        r = rw * 0.60
        cx, cy = rw * (0.98 + deslocar) + r * 0.15, rh * 0.5
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=cor + (255,))
    folga = max(10, int(min(rw, rh) * (0.035 if chave == "login" else 0.06)))
    largura = max(3, int(min(rw, rh) * (0.006 if chave == "login" else 0.012)))
    d.ellipse([cx - r - folga, cy - r - folga, cx + r + folga, cy + r + folga], outline=linha + (255,), width=largura)
    regiao.alpha_composite(camada)
    return cx, cy, r


def _linhas_sutis(regiao, cor, chave):
    """Linhas diagonais finas derivadas da marca (referência Ceasa), nunca pontos."""
    from PIL import ImageDraw
    rw, rh = regiao.size
    d = ImageDraw.Draw(regiao)
    passo = max(22, int((rh if chave == "login" else rw) * 0.05))
    largura = max(2, passo // 9)
    for k in range(-rh, rw + rh, passo):
        d.line([(k, rh), (k + rh * 0.6, 0)], fill=cor + (255,), width=largura)


def _mascara_arco(tamanho, chave):
    from PIL import Image, ImageDraw, ImageFilter
    rw, rh = tamanho
    m = Image.new("L", tamanho, 0)
    d = ImageDraw.Draw(m)
    if chave == "login":
        r = rh * 1.1
        cx, cy = rw * 0.18 + r, rh * 0.5
    else:
        r = rw * 1.4
        cx, cy = rw * 0.10 + r, rh * 0.5
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return m.filter(ImageFilter.GaussianBlur(1.5))


def _fim_do_texto(peca, inicio):
    """Primeira coluna depois de inicio sem texto do painel (cor da tinta) por uma faixa de
    3% da largura: o texto maior do lab pode passar do painel e não pode ser cortado."""
    import numpy as np
    arr = np.asarray(peca.convert("RGB"), dtype=np.int16)
    w = arr.shape[1]
    fundo = arr[6, 6]
    tintas = [np.array(c, dtype=np.int16) for c in ((255, 255, 255), (16, 20, 24), (28, 28, 30))]
    tinta = max(tintas, key=lambda c: int(np.abs(c - fundo).sum()))
    tem = (np.abs(arr - tinta).sum(axis=2) < 90).any(axis=0)
    folga = max(8, int(w * 0.03))
    x, vazio = inicio, 0
    while x < int(w * 0.70):
        vazio = vazio + 1 if not tem[x] else 0
        if vazio >= folga:
            return x - folga + max(4, folga // 3)
        x += 1
    return inicio


def _compor_canto(caminho, chave, paleta, fotos, modelo, cena=None):
    from PIL import Image, ImageDraw
    peca = Image.open(caminho).convert("RGBA")
    w, h = peca.size
    xp = _fim_do_texto(peca, int(w * PINTAR_DE[chave]))
    xc = max(int(w * INICIO_LIVRE[chave]), xp + int(w * 0.02))
    fundo = peca.getpixel((6, 6))[:3]
    destaque = _rgb(paleta.get("destaque") or paleta.get("principal"))
    arco_cor, linha, sutil = _tons_lab(fundo, destaque)
    ImageDraw.Draw(peca).rectangle([xp, 0, w, h], fill=fundo + (255,))
    regiao = Image.new("RGBA", (w - xc, h), (0, 0, 0, 0))
    rw, rh = regiao.size
    login = chave == "login"
    if modelo == "em_uso" and cena is not None:
        foto = cena.convert("RGB")
        escala = max(rw / foto.size[0], rh / foto.size[1])
        foto = foto.resize((int(foto.size[0] * escala) + 1, int(foto.size[1] * escala) + 1), Image.LANCZOS)
        ox, oy = (foto.size[0] - rw) // 2, (foto.size[1] - rh) // 2
        foto = foto.crop((ox, oy, ox + rw, oy + rh)).convert("RGBA")
        mascara = _mascara_arco(regiao.size, chave)
        borda = Image.new("RGBA", regiao.size, (0, 0, 0, 0))
        folga = max(8, int(min(rw, rh) * (0.02 if login else 0.04)))
        borda.paste(Image.new("RGBA", regiao.size, linha + (255,)), (-folga, 0), mascara)
        regiao.alpha_composite(borda)
        foto.putalpha(mascara)
        regiao.alpha_composite(foto)
    else:
        if modelo == "padrao_marca":
            _linhas_sutis(regiao, sutil, chave)
        cx, cy, r = _arco(regiao, chave, arco_cor, linha, deslocar=0.08 if modelo == "vitrine" else 0.0)
        base = rh * (0.84 if login else 0.92)
        if modelo == "diagonal":
            from PIL import ImageFilter
            girado = fotos[0].rotate(16, expand=True, resample=Image.BICUBIC)
            alvo_w, alvo_h = rw * (1.02 if login else 0.62), rh * (0.80 if login else 0.98)
            fator = min(alvo_w / girado.size[0], alvo_h / girado.size[1])
            girado = girado.resize((max(1, int(girado.size[0] * fator)), max(1, int(girado.size[1] * fator))), Image.LANCZOS)
            gx = int(rw - girado.size[0] * (0.90 if login else 0.95))
            gy = int((rh - girado.size[1]) * (0.62 if login else 0.5))
            sombra = Image.new("RGBA", regiao.size, (0, 0, 0, 0))
            sombra.paste(Image.new("RGBA", girado.size, (0, 0, 0, 60)), (gx + 18, gy + 26), girado)
            regiao.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(22)))
            camada = Image.new("RGBA", regiao.size, (0, 0, 0, 0))
            camada.paste(girado, (gx, gy), girado)
            regiao.alpha_composite(camada)
        elif modelo == "vitrine" and len(fotos) >= 3:
            n = 3
            if login:
                alto = rh * 0.30
                _colar_com_sombra(regiao, fotos[0], rw * 0.55, rh * 0.52, rh * 0.40, 0.82)
                for i in range(1, n):
                    _colar_com_sombra(regiao, fotos[i], rw * (0.32 + 0.46 * (i - 1)), base, alto, 0.46)
            else:
                for i in range(n):
                    _colar_com_sombra(regiao, fotos[i], rw * (0.30 + 0.27 * i), base, rh * 0.84, 0.30)
        elif modelo == "trio" and len(fotos) >= 3:
            alto = rh * (0.56 if login else 0.86)
            _colar_com_sombra(regiao, fotos[1], rw * (0.32 if login else 0.24), rh * (0.50 if login else 0.90), alto * 0.72, 0.50 if login else 0.36)
            _colar_com_sombra(regiao, fotos[2], rw * (0.74 if login else 0.80), rh * (0.50 if login else 0.90), alto * 0.72, 0.50 if login else 0.36)
            _colar_com_sombra(regiao, fotos[0], rw * 0.55, base, alto, 0.80 if login else 0.50)
        else:
            alto = rh * (0.64 if login else 0.88)
            _colar_com_sombra(regiao, fotos[0], rw * 0.55, base, alto, 0.92 if login else 0.50)
    peca.alpha_composite(regiao, (xc, 0))
    peca.convert("RGB").save(caminho)



# --- Rodada 3: banner inteiro pedido do zero à Images API (logo + briefing), logo original colada por cima ---
DO_ZERO_TAMANHO = {"login": (2400, 1800), "cabecalho": (1920, 320)}


def _caixa_logo(chave, W, H, logo):
    from PIL import Image
    ref = logo.copy()
    if chave == "login":
        ref.thumbnail((int(W * 0.30), int(H * 0.20)), Image.LANCZOS)
        return ref, (int(W * 0.06), int(H * 0.07))
    ref.thumbnail((int(W * 0.14), int(H * 0.55)), Image.LANCZOS)
    return ref, (int(W * 0.04), (H - ref.size[1]) // 2)


def _logo_clara(logo):
    dados = [px for px in logo.convert("RGBA").getdata() if px[3] > 128]
    if not dados:
        return False
    return sum(_lum(px[:3]) for px in dados) / len(dados) > 0.6


CENAS_DO_ZERO = (
    "um centro de distribuição organizado, com paletes e corredores, luz de fim de tarde",
    "a entrega chegando na loja de um cliente: van ou caminhão descarregando caixas na porta",
    "um lojista recebendo e conferindo a mercadoria no balcão da própria loja",
    "o ambiente onde os produtos são usados pelo cliente final, sem pessoas, bem iluminado",
    "detalhe próximo dos produtos do segmento bem arrumados, fotografia com profundidade de campo",
    "uma equipe pequena e diversa conversando no salão de vendas, ninguém olhando para a câmera",
)
PESSOAS_DO_ZERO = ("uma mulher de meia-idade", "um jovem", "uma jovem", "um senhor grisalho", "duas pessoas conversando")

INSTRUCAO_CONFERIR_DO_ZERO = """Você confere um banner do portal B2B da empresa "{cliente}" antes de ir ao ar.
A primeira imagem é a logo correta da empresa; a segunda é o banner.
Reprove (ok=false) se: a logo do banner estiver ausente ou diferente da correta (letras, símbolo ou cores trocados);
houver texto com erro de português, letra trocada, palavra inventada ou texto ilegível; texto cortado na borda;
houver outra marca ou logotipo de terceiros em destaque.
Responda só JSON: {{"ok": true, "motivo": ""}}"""


def _o_que_vende(entrada):
    try:
        catalogo = entrada.get("catalogo")
        if isinstance(catalogo, str):
            catalogo = json.loads(catalogo)
        nomes = [p["nome"] for p in _produtos_do_json(catalogo or {}) if p.get("nome")][:6]
    except Exception:
        nomes = []
    segmento = entrada.get("segmento") or "produtos para revenda"
    return segmento + (f" (por exemplo: {', '.join(nomes)})" if nomes else "")


def _b64_pil(img, lado=1024):
    from PIL import Image
    copia = img.convert("RGBA")
    base = Image.new("RGB", copia.size, (255, 255, 255))
    base.paste(copia, mask=copia.getchannel("A"))
    base.thumbnail((lado, lado))
    buf = io.BytesIO()
    base.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _conferir_do_zero(img, logo, cliente):
    """Motivo da reprovação, ou None (aprovado ou conferência indisponível)."""
    try:
        resposta, _ = _ia_visao(INSTRUCAO_CONFERIR_DO_ZERO.format(cliente=cliente or "cliente"),
                                [("Logo correta da empresa:", _b64_pil(logo, 512)), ("Banner:", _b64_pil(img))])
    except Exception:
        return None
    if isinstance(resposta, dict) and resposta.get("ok") is False:
        return str(resposta.get("motivo") or "reprovado")[:200]
    return None


def _ajustar_do_zero(img, chave):
    from PIL import Image
    W, H = DO_ZERO_TAMANHO[chave]
    if chave == "login":
        return img.resize((W, H), Image.LANCZOS)
    alto = int(img.size[1] * W / img.size[0])
    img = img.resize((W, alto), Image.LANCZOS)
    if alto > H:
        topo = (alto - H) // 2
        return img.crop((0, topo, W, topo + H))
    return img.resize((W, H), Image.LANCZOS)


def _banner_livre(chave, logo, cliente, vende, pedido="", marca_hex=None):
    """Prompt mínimo: a logo, o que a empresa vende e o objetivo do banner. O resto é com a IA."""
    from PIL import Image
    tela = Image.new("RGB", (1600, 1200), (255, 255, 255))
    ref = logo.copy()
    ref.thumbnail((900, 600), Image.LANCZOS)
    tela.paste(ref, ((1600 - ref.size[0]) // 2, (1200 - ref.size[1]) // 2), ref)
    formato = ("formato paisagem 4:3, tela de login" if chave == "login"
               else "faixa horizontal muito larga 6:1, cabeçalho do site (o conteúdo importante na faixa central da altura)")
    prompt = (f"Esta é a logo da empresa {cliente}, que vende {vende} para lojistas e revendedores. "
              f"Crie um banner para o portal de pedidos B2B dela, {formato}. Objetivo do banner: receber os clientes "
              f"que entram no portal e convidar a fazer os pedidos por ali. Use esta logo, sem alterá-la."
              + (f" A cor principal da marca é {marca_hex}." if marca_hex else "")
              + (f" Pedido do executivo: {pedido}." if pedido else ""))
    img = _editar_imagem(tela, prompt, lado=1600)
    return _ajustar_do_zero(img, chave) if img is not None else None


def _banner_guiado(chave, logo, cliente, vende, marca_hex, cena, pedido=""):
    """Layout fixo (logo original colada por cima), cena sorteada para os portais não ficarem iguais."""
    W, H = DO_ZERO_TAMANHO[chave]
    from PIL import Image
    clara = _logo_clara(logo)
    fundo_logo = _rgb(marca_hex) if clara and marca_hex else ((28, 28, 30) if clara else (255, 255, 255))
    tela = Image.new("RGB", (W, H), fundo_logo)
    ref, pos = _caixa_logo(chave, W, H, logo)
    tela.paste(ref, pos, ref)
    tom = "escuro na cor da marca" if clara else "claro e limpo"
    if chave == "login":
        layout = (f"formato paisagem 4:3. Lado esquerdo (40%): fundo {tom} e liso. A logo ocupa o canto superior esquerdo "
                  f"(até 30% da altura): deixe essa área VAZIA na cor {_hex(fundo_logo)}, sem desenhar logo nem texto. "
                  f"Logo abaixo dela, sem vão grande, o título 'PORTAL DO CLIENTE' em caixa alta, grande, e a frase "
                  f"'Compre com agilidade e segurança, direto do seu fornecedor.' alinhados à esquerda. Lado direito (60%): ")
    else:
        layout = (f"faixa horizontal muito larga, 6:1 (cabeçalho de site); todo o conteúdo importante na faixa central da altura. "
                  f"Terço esquerdo: fundo {tom}, liso e totalmente VAZIO na cor {_hex(fundo_logo)} (sem logo, sem texto). Restante: ")
    prompt = (f"A imagem mostra a logo da empresa só como referência de cores. Crie do zero um banner profissional de portal B2B "
              f"de pedidos, como feito por um designer gráfico sênior, {layout}uma cena fotográfica de {cena}, no contexto de "
              f"{cliente}, que vende {vende} para lojistas e revendedores. Se aparecer gente, use {random.choice(PESSOAS_DO_ZERO)}; "
              f"evite o clichê de homem de avental com tablet. Composição coesa, iluminação única, transição suave entre os "
              f"dois lados; sem produtos colados, sem colagem. Use as cores da logo como paleta. Não reproduza a logo nem o "
              f"nome da empresa. Sem texto além do pedido, sem marca d'água, tipografia correta em português."
              + (f" Pedido do executivo: {pedido}." if pedido else ""))
    img = _editar_imagem(tela, prompt, lado=1920)
    if img is None:
        return None
    img = _ajustar_do_zero(img, chave)
    ref, pos = _caixa_logo(chave, W, H, logo)
    img.paste(ref, pos, ref)
    return img


def _lab_do_zero(pecas, logo_arq, entrada, paleta, minimo=False, pedido=""):
    """Gera login e cabeçalho do zero, conferidos (logo fiel, texto sem erro); até 2 tentativas por peça.
    Devolve o modo usado ('do_zero_livre' ou 'do_zero') ou None se não saiu."""
    from PIL import Image
    logo = Image.open(logo_arq).convert("RGBA")
    cliente = entrada.get("cliente") or ""
    vende = _o_que_vende(entrada)
    marca = paleta.get("principal")
    cena = random.choice(CENAS_DO_ZERO)
    alvos = [c for c in ("login", "cabecalho") if c in pecas]

    def uma(chave):
        tentativas = ([("livre", lambda: _banner_livre(chave, logo, cliente, vende, pedido, marca))] * 2 if minimo else []) + \
                     [("guiado", lambda: _banner_guiado(chave, logo, cliente, vende, marca, cena, pedido))] * 2
        for modo, gerar in tentativas:
            img = gerar()
            if img is None:
                continue
            motivo = _conferir_do_zero(img, logo, cliente)
            if not motivo:
                return modo, img
            evento("banners", f"banner do zero ({chave}, {modo}) reprovado na conferência: {motivo}; refazendo", "aviso")
        return None, None

    with selecao.ThreadPoolExecutor(2) as pool:
        feitas = dict(zip(alvos, pool.map(uma, alvos)))
    if not all(feitas[c][1] is not None for c in alvos):
        return None
    for chave, (_, img) in feitas.items():
        img.resize(Image.open(pecas[chave]).size, Image.LANCZOS).save(pecas[chave])
    modos = {m for m, _ in feitas.values()}
    evento("banners", f"banner criado do zero ({', '.join(sorted(modos))}); cena: {cena if 'guiado' in modos else 'livre'}")
    return "do_zero_livre" if modos == {"livre"} else "do_zero"


def _modelo_da_regra(regras, indice):
    pesos = (regras or {}).get("pesos") or {}
    ordem = sorted(MODELOS_LAB, key=lambda m: -float(pesos.get(m, 3)))
    vivos = [m for m in ordem if float(pesos.get(m, 3)) >= 2.2] or ordem[:1]
    return vivos[indice % len(vivos)]


def lab_banner(entrada):
    global LAB_ATIVO, identidade_visual
    import subir_banners
    regras = entrada.get("regras") or {}
    if isinstance(regras, str):
        try:
            regras = json.loads(regras) if regras.strip() else {}
        except ValueError:
            regras = {}
    navegador = entrada.get("cores_navegador")
    if isinstance(navegador, str):
        try:
            navegador = json.loads(navegador)
        except ValueError:
            navegador = None
    LAB_ATIVO = True
    identidade_visual = lambda site, logo: _identidade_lab(site, logo, navegador)
    pedido_id = entrada["pedido_id"]
    pasta = pasta_pedido(f"lab-{entrada['lab_id']}")
    logo = restaurar_logo(entrada, pasta)
    if not logo:
        logo = logo_tipografica(entrada.get("cliente"), pasta)
    caminho = gravar_catalogo(entrada["catalogo"], pedido_id)
    gerada, saida, paleta = gerar_com_identidade(entrada, caminho, logo, variar=False)
    if not gerada:
        raise RuntimeError("peça base não saiu: " + str(saida)[-400:])
    pecas, _ = subir_banners.pecas_da_pasta(gerada)
    if (entrada.get("modelo") or "do_zero") == "do_zero":
        modo = _lab_do_zero(pecas, logo, entrada, paleta, minimo=True)
        if modo:
            _mobile_seguro(gerada, logo, entrada.get("cliente") or "")
            telas = pecas_para_tela(gerada)
            return {"modelo": modo, "cor": cor_da_pasta(gerada), "banners_tar": empacotar(gerada),
                    "login": (telas.get("login") or {}).get("previa_base64"),
                    "cabecalho": (telas.get("cabecalho") or {}).get("previa_base64")}
        evento("banners", "laboratório: criação do zero falhou; caiu na composição com fotos", "aviso")
    modelo = _modelo_da_regra(regras, int(entrada.get("indice") or 0))
    fundo_hex = paleta.get("principal") or "#FFFFFF"
    try:
        from PIL import Image
        fundo_hex = _hex(Image.open(pecas.get("login") or next(iter(pecas.values()))).convert("RGB").getpixel((6, 6)))
    except Exception:
        pass
    quantas = 4 if modelo == "vitrine" else 3 if modelo == "trio" else 1
    fotos, originais = _fotos_lab(entrada["catalogo"], quantas, fundo_hex)
    cena = None
    if not fotos:
        modelo = "so_marca"
        evento("banners", "laboratório: nenhuma foto de produto boa o bastante; banner só com a marca", "aviso")
    else:
        if modelo in ("trio", "vitrine") and len(fotos) < 3:
            modelo = "diagonal"
        if modelo == "em_uso":
            cena = _produto_em_uso(originais[0], fundo_hex, entrada.get("segmento"))
            if cena is None:
                modelo = "destaque"
        for chave, arquivo in pecas.items():
            if chave in INICIO_LIVRE:
                _compor_canto(arquivo, chave, paleta, fotos, modelo, cena)
        evento("banners", f"laboratório: modelo {modelo} com {len(fotos)} foto(s), fundo {fundo_hex}")
    _mobile_seguro(gerada, logo, entrada.get("cliente") or "")
    telas = pecas_para_tela(gerada)
    return {"modelo": modelo, "cor": cor_da_pasta(gerada), "banners_tar": empacotar(gerada),
            "login": (telas.get("login") or {}).get("previa_base64"),
            "cabecalho": (telas.get("cabecalho") or {}).get("previa_base64")}


def lab_aplicar(entrada):
    import atendimento
    pasta = pasta_pedido(f"lab-aplicar-{entrada['lab_id']}")
    banners = desempacotar(entrada["banners_tar"], pasta / "banners")
    portal_id = entrada["portal_id"]
    _mobile_seguro(banners, None, entrada.get("cliente") or "", so_se_faltar=True)
    publicadas = atendimento.publicar_pecas(ORG, portal_id, banners)
    escolhas = {k: v["file_id"] for k, v in (publicadas or {}).items() if v and v.get("file_id")}
    if not escolhas:
        raise RuntimeError("as peças não subiram para o portal")
    try:
        relato = atendimento.aplicar_pecas(ORG, portal_id, escolhas, cor=cor_da_pasta(banners))
    except atendimento.GravacaoPelaMetade as erro:
        return {"aplicado_parcial": True, "erro": str(erro), "publicadas": publicadas}
    return {"relato": relato, "publicadas": publicadas, "escolhas": escolhas}


# --- Banner mobile: o banner principal da Zydon tem imagem Web (imageLarge 1920x320) e Mobile (imageSmall 720x270) ---
MOBILE = "cabecalho_mobile"
MOBILE_TAMANHO = (720, 270)
ACOES_COM_BANNER = {"previa", "criar", "banner", "lab_banner", "lab_aplicar"}


def _registrar_mobile():
    """Ensina o repositório (sem editá-lo) que existe a peça mobile: formato, destino imageSmall
    e a aplicação no mesmo banner do cabeçalho, conferida por GET."""
    import formatos
    import subir_banners
    import atendimento
    import portal as mod_portal
    if MOBILE not in formatos.POR_CHAVE:
        formatos.POR_CHAVE[MOBILE] = formatos.Formato(MOBILE, *MOBILE_TAMANHO, painel=MOBILE_TAMANHO[0], proporcao_pedida="")
    subir_banners.DESTINOS.setdefault(MOBILE, {"onde": "banner", "campo": "imageSmall", "dimensao": MOBILE_TAMANHO})
    if MOBILE not in atendimento.DESTINOS_BANNER:
        atendimento.DESTINOS_BANNER = tuple(atendimento.DESTINOS_BANNER) + (MOBILE,)
    original = subir_banners.aplicar
    if getattr(original, "_mobile", False):
        return

    def aplicar(jwt, ids, aparencia=None, banner=None, ecoar=None, cor=None):
        ids = dict(ids or {})
        movel = ids.pop(MOBILE, None)
        if ids or cor or not movel:
            relato = original(jwt, ids, aparencia=aparencia, banner=banner, ecoar=ecoar, cor=cor)
        else:
            relato = {"gravados": [], "confere": {}}
        if not movel:
            return relato
        alvo = subir_banners._banner_alvo(jwt)
        if not alvo:
            relato["confere"][MOBILE] = False
            return relato
        identificador = alvo.get("id") or alvo.get("bannerId")
        try:
            mod_portal.atualizar_banner(jwt, identificador, alvo, {"imageSmall": movel})
        except mod_portal.ErroDoPortal as erro:
            if not relato["gravados"]:
                raise
            raise subir_banners.GravacaoPelaMetade(erro, relato["gravados"], [MOBILE]) from erro
        relato["gravados"].append(MOBILE)
        if ecoar:
            ecoar("  [OK] banner.images[0].imageSmall")
        agora = mod_portal.obter_banner(jwt, identificador)
        relato["confere"][MOBILE] = ((agora.get("images") or [{}])[0]).get("imageSmall") == movel
        return relato
    aplicar._mobile = True
    subir_banners.aplicar = aplicar


def _montar_mobile(cabecalho, logo, marca_hex, modo):
    """720x270: painel liso com a logo original e a frase; à direita, a cena do próprio cabeçalho
    (modo 'cena'). No modo 'marca' a peça inteira é o painel, sem foto."""
    from PIL import Image, ImageDraw
    import formatos
    import tipografia as tipo
    W, H = MOBILE_TAMANHO
    clara = _logo_clara(logo)
    fundo = _rgb(marca_hex) if clara and marca_hex else ((28, 28, 30) if clara else (255, 255, 255))
    tinta = (255, 255, 255) if _lum(fundo) < 0.4 else (16, 20, 24)
    peca = Image.new("RGB", (W, H), fundo)
    painel = 300 if modo == "cena" else W
    if modo == "cena":
        largura_cab, altura_cab = cabecalho.size
        alvo_w, alvo_h = W - painel, H
        corte = min(int(largura_cab * 0.30), round(altura_cab * alvo_w / alvo_h))
        cena = cabecalho.crop((largura_cab - corte, 0, largura_cab, altura_cab))
        escala = max(alvo_w / cena.width, alvo_h / cena.height)
        cena = cena.resize((max(alvo_w, round(cena.width * escala)), max(alvo_h, round(cena.height * escala))), Image.LANCZOS)
        esquerda, topo = (cena.width - alvo_w) // 2, (cena.height - alvo_h) // 2
        peca.paste(cena.crop((esquerda, topo, esquerda + alvo_w, topo + alvo_h)), (painel, 0))
    margem = 32
    util = (painel if modo == "cena" else int(W * 0.55)) - margem * 2
    ref = logo.copy()
    ref.thumbnail((util, int(H * 0.38)), Image.LANCZOS)
    desenho = ImageDraw.Draw(peca)
    fonte, linhas, _ = tipo.ajustar(desenho, formatos.FRASE_CABECALHO, util, 24, 16, "Medium", 2)
    frase = formatos.FRASE_CABECALHO
    if "," in frase:
        partes = [frase[:frase.index(",") + 1].strip(), frase[frase.index(",") + 1:].strip()]
        for corpo in range(24, 15, -2):
            candidata = tipo.fonte(corpo, "Medium")
            if all(desenho.textlength(parte, font=candidata) <= util for parte in partes):
                fonte, linhas = candidata, partes
                break
    passo = int(fonte.size * 1.3)
    y = (H - (ref.height + 22 + passo * len(linhas))) // 2
    if modo == "cena":
        peca.paste(ref, (margem, y), ref)
        x_texto = lambda linha: margem
    else:
        peca.paste(ref, ((W - ref.width) // 2, y), ref)
        x_texto = lambda linha: (W - int(desenho.textlength(linha, font=fonte))) // 2
    y += ref.height + 22
    for i, linha in enumerate(linhas):
        desenho.text((x_texto(linha), y + i * passo), linha, font=fonte, fill=tinta)
    return peca


INSTRUCAO_CONFERIR_MOBILE = """Você confere o banner MOBILE (720x270) do portal B2B da empresa "{cliente}" antes de ir ao ar.
A primeira imagem é a logo correta da empresa; a segunda é o banner.
Reprove (ok=false) se: a logo estiver ausente, deformada ou diferente da correta; houver texto com erro, ilegível ou
cortado; aparecer QUALQUER pedaço de letra, palavra, botão ou logo cortado pela borda da foto ou da peça (sobra de
outro banner recortado); houver marca de terceiros em destaque; houver caixa vazia ou imagem quebrada.
Responda só JSON: {{"ok": true, "motivo": ""}}"""


def _conferir_mobile(img, logo, cliente):
    try:
        resposta, _ = _ia_visao(INSTRUCAO_CONFERIR_MOBILE.format(cliente=cliente or "cliente"),
                                [("Logo correta da empresa:", _b64_pil(logo, 512)), ("Banner mobile:", _b64_pil(img, 720))])
    except Exception:
        return None
    if isinstance(resposta, dict) and resposta.get("ok") is False:
        return str(resposta.get("motivo") or "reprovado")[:200]
    return None


def peca_mobile(pasta, logo=None, cliente="", so_se_faltar=False):
    """Gera a peça mobile do banner a partir do cabeçalho já aprovado e a registra no manifesto.
    Conferida pela IA (logo fiel, texto legível); reprovada nos dois modos, não vai ao portal."""
    from PIL import Image
    pasta = Path(pasta)
    arquivo = pasta / "manifesto.json"
    try:
        manifesto = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pecas = manifesto.setdefault("pecas", {})
    if so_se_faltar and MOBILE in pecas and (pasta / "aprovados" / pecas[MOBILE]["arquivo"]).exists():
        return pasta / "aprovados" / pecas[MOBILE]["arquivo"]
    cab = pecas.get("cabecalho")
    origem = pasta / "aprovados" / cab["arquivo"] if cab else None
    fonte_logo = next((c for c in (pasta / "logo-normalizada.png", Path(logo) if logo else None) if c and c.exists()), None)
    if not origem or not origem.exists() or not fonte_logo:
        return None
    logo_img = Image.open(fonte_logo).convert("RGBA")
    cabecalho = Image.open(origem).convert("RGB")
    marca = cor_da_pasta(pasta)
    motivos = []
    for modo in ("cena", "marca"):
        img = _montar_mobile(cabecalho, logo_img, marca, modo)
        motivo = _conferir_mobile(img, logo_img, cliente)
        if not motivo:
            break
        motivos.append(f"{modo}: {motivo}")
        evento("banners", f"banner mobile ({modo}) reprovado na conferência: {motivo}", "aviso")
    else:
        pecas.pop(MOBILE, None)
        arquivo.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        evento("banners", "banner mobile reprovado: " + "; ".join(motivos) + " · não vai para o portal", "erro")
        return None
    destino = pasta / "aprovados" / f"{MOBILE}.png"
    img.save(destino, optimize=True)
    pecas[MOBILE] = {"origem": f"derivado_{modo}", "arquivo": destino.name, "tentativas": len(motivos) + 1,
                     "dimensao": list(MOBILE_TAMANHO)}
    arquivo.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    evento("banners", f"banner mobile {MOBILE_TAMANHO[0]}x{MOBILE_TAMANHO[1]} pronto ({modo}) e conferido")
    return destino


def _mobile_seguro(pasta, logo=None, cliente="", so_se_faltar=False):
    try:
        return peca_mobile(pasta, logo, cliente, so_se_faltar)
    except Exception as erro:
        evento("banners", f"banner mobile falhou ({type(erro).__name__}: {str(erro)[:160]})", "aviso")
        return None


ACOES = {"loja_publica": loja_publica, "url_portal": url_portal, "trocar_logo": trocar_logo, "miniaturas": miniaturas, "extrair": extrair, "avaliar": avaliar, "previa": previa, "criar": criar, "banner": banner, "telufia": telufia, "lab_banner": lab_banner, "lab_aplicar": lab_aplicar}


def _restaurar_cores_navegador(entrada):
    """As cores lidas pelo navegador ficam guardadas no pedido; cada etapa (banner, prévia,
    criação) pode rodar em outra máquina, então o cache local é regravado antes de começar."""
    import hashlib
    cores = entrada.get("cores_navegador")
    if isinstance(cores, str):
        try:
            cores = json.loads(cores)
        except ValueError:
            cores = None
    if not cores or not entrada.get("site"):
        return
    try:
        guardado = TRABALHO / "cores" / (hashlib.md5(("v2:" + entrada["site"].strip().lower()).encode()).hexdigest() + ".json")
        guardado.parent.mkdir(parents=True, exist_ok=True)
        guardado.write_text(json.dumps([list(_rgb(c)) for c in cores]), encoding="utf-8")
    except Exception:
        pass


def main():
    acao, arquivo_entrada, arquivo_saida = sys.argv[1:4]
    entrada = json.loads(Path(arquivo_entrada).read_text(encoding="utf-8"))
    _restaurar_cores_navegador(entrada)
    if acao in ACOES_COM_BANNER:
        try:
            _registrar_mobile()
        except Exception as erro:
            evento("banners", f"peça mobile indisponível ({type(erro).__name__}: {erro})", "aviso")
    try:
        resultado = {"ok": True, **ACOES[acao](entrada)}
    except Exception as erro:
        resultado = {"ok": False, "erro": f"{type(erro).__name__}: {erro}",
                     "rastro": traceback.format_exc()[-2500:]}
    Path(arquivo_saida).write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()

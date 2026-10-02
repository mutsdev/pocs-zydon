"""Navegador sem tela (Playwright + Chromium) como fonte principal da home do cliente.

Abre a home como uma pessoa, tira a captura do topo e lista as imagens do cabeçalho e os
links. O barroso-chat olha a captura e diz qual é a logo, quais são as cores da marca e
quais links levam ao catálogo de produtos (ex.: menu "Produtos" da Mabel). O navegador
abre essas páginas, rola até o fim (fotos carregadas sob demanda) e lê os cartões de produto.

O Chromium roda num processo à parte, em modo enxuto (um processo, sem JIT): o servidor
das funções tem ~470 MB e o modo padrão morre por memória. Cada fase abre e fecha o
navegador, para nada dele ficar na memória durante a busca de produtos.
"""

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions",
        "--disable-background-networking", "--disable-features=site-per-process,Translate,MediaRouter",
        "--renderer-process-limit=1", "--disable-software-rasterizer", "--no-zygote", "--single-process",
        "--js-flags=--jitless --max-old-space-size=128"]
LARGURA, ALTURA = 1280, 800
MAXIMO_PAGINAS = 3

JS_HOME = r"""() => {
  const topo = 260, cands = [], links = [], vistos = new Set();
  let i = 0;
  const marcar = (el, tipo, src) => {
    const r = el.getBoundingClientRect();
    if (r.top > topo || r.bottom < 0 || r.width < 30 || r.height < 12 || r.width > 700) return;
    el.setAttribute('data-nav-id', String(i));
    cands.push({n: i++, tipo, src: src || '', alt: (el.getAttribute('alt') || el.getAttribute('aria-label') || '').slice(0, 80),
      classe: String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').slice(0, 80),
      x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
      svg: tipo === 'svg' ? el.outerHTML.slice(0, 60000) : ''});
  };
  const fonte = (img) => {
    const atual = img.currentSrc || img.src || '';
    if (atual && !atual.startsWith('data:')) return atual;
    const preguica = img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || img.getAttribute('data-original')
      || (img.getAttribute('data-srcset') || img.getAttribute('srcset') || '').split(',')[0].trim().split(' ')[0];
    return preguica ? new URL(preguica, location.href).href : atual;
  };
  for (const img of document.images) marcar(img, 'img', fonte(img));
  for (const svg of document.querySelectorAll('svg')) if (!svg.parentElement.closest('svg')) marcar(svg, 'svg', '');
  for (const el of document.querySelectorAll('header *, nav *, a, div, span')) {
    if (cands.length > 40) break;
    const bg = getComputedStyle(el).backgroundImage;
    const m = bg && bg.match(/url\(["']?([^"')]+)["']?\)/);
    if (m && !m[1].startsWith('data:')) marcar(el, 'fundo', new URL(m[1], location.href).href);
  }
  for (const a of document.querySelectorAll('a[href]')) {
    const texto = (a.innerText || a.getAttribute('title') || '').trim().replace(/\s+/g, ' ');
    const href = a.href.split('#')[0];
    if (!texto || texto.length > 40 || !href.startsWith('http') || vistos.has(href)) continue;
    vistos.add(href);
    links.push({texto, href});
    if (links.length >= 90) break;
  }
  const cor = (el, p) => el ? getComputedStyle(el)[p] : '';
  const botoes = [...document.querySelectorAll('button, .btn, [class*=button], [class*=botao]')]
    .map(b => cor(b, 'backgroundColor')).filter(c => c && !/rgba\(0, 0, 0, 0\)|transparent/.test(c)).slice(0, 6);
  const raiz = getComputedStyle(document.documentElement);
  const variaveis = {};
  for (const folha of document.styleSheets) {
    let regras; try { regras = folha.cssRules; } catch (e) { continue; }
    for (const r of regras || []) {
      if (r.selectorText !== ':root' || !r.style) continue;
      for (const nome of r.style) if (/primar|brand|marca|principal|main|secund|accent/i.test(nome))
        variaveis[nome] = raiz.getPropertyValue(nome).trim();
    }
  }
  return {titulo: document.title, cands, links, botoes, variaveis,
    cabecalho: cor(document.querySelector('header') || document.querySelector('nav'), 'backgroundColor')};
}"""

JS_LISTA = r"""() => {
  const out = [], vistos = new Set();
  for (const img of document.images) {
    const r = img.getBoundingClientRect();
    const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
    if (!src || src.startsWith('data:') || vistos.has(src)) continue;
    if (Math.max(img.naturalWidth || 0, r.width) < 90 || r.width < 50) continue;
    let card = img.parentElement;
    for (let k = 0; k < 5 && card && (card.innerText || '').trim().length < 3; k++) card = card.parentElement;
    const a = img.closest('a[href]') || (card && card.querySelector('a[href]'));
    let nome = (img.alt || img.title || '').trim();
    if (nome.length < 3 && card) {
      const t = card.querySelector('h1,h2,h3,h4,h5,[class*=name],[class*=nome],[class*=title],[class*=titulo]') || card;
      nome = ((t.innerText || '').split('\n').map(s => s.trim()).filter(s => s.length > 2)[0]) || '';
    }
    const preco = ((card && card.innerText) || '').match(/R\$\s*[\d.]+,\d{2}/);
    vistos.add(src);
    out.push({nome: nome.slice(0, 140), url: a ? a.href.split('#')[0] : '', imagem: src, preco: preco ? preco[0] : null});
  }
  return {titulo: document.title, itens: out.slice(0, 150)};
}"""


def _abrir(p, url, pg=None):
    navegador = p.chromium.launch(args=ARGS)
    contexto = navegador.new_context(viewport={"width": LARGURA, "height": ALTURA}, device_scale_factor=1,
                                     locale="pt-BR")
    contexto.route("**/*", lambda r: r.abort() if r.request.resource_type in ("media", "font") else r.continue_())
    pagina = contexto.new_page()
    pagina.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        pagina.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    return navegador, pagina


def _processo_home(url, pasta):
    from playwright.sync_api import sync_playwright
    pasta = Path(pasta)
    with sync_playwright() as p:
        navegador, pagina = _abrir(p, url)
        pagina.screenshot(path=str(pasta / "topo.jpg"), type="jpeg", quality=72)
        dados = pagina.evaluate(JS_HOME)
        dados["final"] = pagina.url
        for c in dados["cands"][:12]:
            destino = pasta / f"cand_{c['n']}.png"
            try:
                pagina.locator(f'[data-nav-id="{c["n"]}"]').first.screenshot(
                    path=str(destino), omit_background=True, timeout=3000)
                c["recorte"] = str(destino)
            except Exception:
                pass
        navegador.close()
    return dados


def _processo_listas(pasta, urls):
    from playwright.sync_api import sync_playwright
    paginas = []
    with sync_playwright() as p:
        for url in urls:
            try:
                navegador, pagina = _abrir(p, url)
                for _ in range(10):
                    pagina.mouse.wheel(0, ALTURA)
                    pagina.wait_for_timeout(350)
                try:
                    pagina.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                dados = pagina.evaluate(JS_LISTA)
                dados["url"] = pagina.url
                paginas.append(dados)
                navegador.close()
            except Exception as erro:
                paginas.append({"url": url, "erro": f"{type(erro).__name__}: {str(erro)[:160]}", "itens": []})
    return paginas


def _rodar(args, prazo):
    r = subprocess.run([sys.executable, __file__] + args, capture_output=True, text=True, timeout=prazo)
    linhas = [l for l in r.stdout.splitlines() if l.startswith("NAVEGADOR ")]
    if not linhas:
        raise RuntimeError(f"navegador saiu com código {r.returncode}: {(r.stderr or r.stdout)[-300:]}")
    return json.loads(linhas[-1][10:])


INSTRUCAO_HOME = """Você vê a captura do topo da página inicial do site do cliente "{cliente}" ({site}),
aberta num navegador, e recortes numerados dos elementos do cabeçalho.

1. LOGO: qual recorte numerado é a logo da empresa "{cliente}" (a marca no cabeçalho, não um banner,
   selo, ícone de rede social nem logo de parceiro)? Use o número do recorte; null se nenhum for a logo.
2. CORES: as 2 cores da identidade visual da marca, olhando a logo e o site (botões, cabeçalho, faixas).
   Ignore branco, preto, cinza e as cores das fotos de produto. Use as cores medidas na página quando
   baterem com o que você vê: {cores_medidas}
3. PRODUTOS: dos links abaixo, quais levam ao CATÁLOGO de produtos (listas de produtos, linhas,
   categorias de produto)? Até {maximo}, o mais completo primeiro. Nunca receitas, blog, notícias,
   institucional, contato, trabalhe conosco, login ou carrinho.

Recortes:
{recortes}

Links:
{links}

Responda SOMENTE JSON:
{{"logo": 3, "cor_principal": "#E2001A", "cor_apoio": "#FFA811", "paginas_produtos": ["https://..."],
  "o_que_vende": "frase curta"}}"""


def _hex_de_rgb(texto):
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", str(texto or ""))
    return "#%02X%02X%02X" % tuple(int(x) for x in m.groups()) if m else None


def _preco(texto):
    m = re.search(r"([\d.]+,\d{2})", str(texto or ""))
    try:
        return float(m.group(1).replace(".", "").replace(",", ".")) if m else None
    except ValueError:
        return None


def _baixar_logo(url, pasta):
    import requests
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                                 "AppleWebKit/537.36 Chrome/128 Safari/537.36"})
        if r.status_code != 200 or len(r.content) < 200:
            return None
        tipo = r.headers.get("content-type", "")
        ext = ".svg" if "svg" in tipo or url.lower().split("?")[0].endswith(".svg") else \
            "." + (re.sub(r"[^a-z]", "", tipo.split("/")[-1].split(";")[0]) or "png")
        destino = Path(pasta) / f"logo_navegador{ext.replace('jpeg', 'jpg')}"
        destino.write_bytes(r.content)
        return str(destino)
    except Exception:
        return None


def explorar(site, cliente, pasta, evento, ia_barroso):
    """{logo_arquivo, logo_url, cores: [#hex], paginas, candidatos, o_que_vende}."""
    import time
    pasta = Path(pasta) / "navegador"
    pasta.mkdir(parents=True, exist_ok=True)
    inicio = time.monotonic()
    home = _rodar(["home", site, str(pasta)], 90)
    evento("navegador", f"home aberta no navegador em {time.monotonic() - inicio:.1f}s: "
                        f"{len(home['cands'])} elementos no cabeçalho, {len(home['links'])} links")
    medidas = [c for c in [_hex_de_rgb(b) for b in home.get("botoes") or []] if c]
    medidas += [v.upper() for v in (home.get("variaveis") or {}).values() if re.match(r"^#[0-9a-fA-F]{6}$", v)]
    recortes = [c for c in home["cands"] if c.get("recorte")][:8]
    texto = INSTRUCAO_HOME.format(
        cliente=cliente, site=site, maximo=MAXIMO_PAGINAS, cores_medidas=", ".join(dict.fromkeys(medidas)) or "nenhuma",
        recortes="\n".join(f"{c['n']}. {c['tipo']} alt=\"{c['alt']}\" classe=\"{c['classe'][:40]}\" "
                           f"arquivo={c['src'].split('?')[0].rsplit('/', 1)[-1][:60]} em x={c['x']} y={c['y']} "
                           f"{c['w']}x{c['h']}" for c in recortes) or "(nenhum)",
        links="\n".join(f"- {l['texto']} -> {l['href']}" for l in home["links"]))
    conteudo = [{"type": "text", "text": texto}, {"type": "text", "text": "Captura do topo da página:"},
                {"type": "image_url", "image_url": {"url": "navegador://topo"}}]
    baixadas = {"navegador://topo": ("image/jpeg", base64.b64encode((pasta / "topo.jpg").read_bytes()).decode())}
    for c in recortes:
        chave = f"navegador://recorte/{c['n']}"
        conteudo += [{"type": "text", "text": f"Recorte {c['n']}:"}, {"type": "image_url", "image_url": {"url": chave}}]
        baixadas[chave] = ("image/png", base64.b64encode(Path(c["recorte"]).read_bytes()).decode())
    t_ia = time.monotonic()
    resposta, custo = ia_barroso([{"role": "user", "content": conteudo}], baixadas)
    evento("navegador", f"barroso-chat leu a captura em {time.monotonic() - t_ia:.1f}s: logo = recorte "
                        f"{resposta.get('logo')}, cores {resposta.get('cor_principal')} / {resposta.get('cor_apoio')}, "
                        f"páginas de produtos: {', '.join(resposta.get('paginas_produtos') or []) or 'nenhuma'}")
    saida = {"custo": custo, "o_que_vende": resposta.get("o_que_vende") or "", "cores": [], "candidatos": [],
             "paginas": []}
    for chave in ("cor_principal", "cor_apoio"):
        valor = str(resposta.get(chave) or "").strip().upper()
        if re.match(r"^#[0-9A-F]{6}$", valor):
            saida["cores"].append(valor)
    escolhido = next((c for c in home["cands"] if str(c["n"]) == str(resposta.get("logo"))), None)
    if escolhido:
        arquivo = None
        if escolhido["tipo"] == "svg" and escolhido.get("svg"):
            arquivo = pasta / "logo_navegador.svg"
            svg = escolhido["svg"]
            if "xmlns=" not in svg[:300]:
                svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
            arquivo.write_text(svg, encoding="utf-8")
            arquivo = str(arquivo)
        elif escolhido.get("src"):
            arquivo = _baixar_logo(escolhido["src"], pasta)
            saida["logo_url"] = escolhido["src"]
        saida["logo_arquivo"] = arquivo or escolhido.get("recorte")
        saida["logo_recorte"] = escolhido.get("recorte")
    host = (urlparse(home.get("final") or site).hostname or "").replace("www.", "")
    validas = {l["href"] for l in home["links"]}
    paginas = [u for u in (resposta.get("paginas_produtos") or []) if u in validas
               and host in (urlparse(u).hostname or "")][:MAXIMO_PAGINAS]
    if paginas:
        t_lista = time.monotonic()
        lidas = _rodar(["listas", str(pasta)] + paginas, 150)
        for pagina in lidas:
            categoria = re.split(r"\s[|\-–]\s", pagina.get("titulo") or "")[0][:60]
            achados = 0
            for item in pagina.get("itens") or []:
                if not item.get("nome") or not str(item.get("imagem", "")).startswith("http"):
                    continue
                caminho = urlparse(item.get("url") or "").path.strip("/")
                if not caminho or (item.get("url") or "").rstrip("/") == pagina["url"].rstrip("/"):
                    continue
                saida["candidatos"].append({"nome": item["nome"], "url": item.get("url") or pagina["url"],
                                            "imagem": item["imagem"], "preco": _preco(item.get("preco")),
                                            "categoria": categoria, "descricao": "", "origem": "site"})
                achados += 1
            saida["paginas"].append({"url": pagina["url"], "itens": achados, "erro": pagina.get("erro")})
        evento("navegador", f"páginas de produtos lidas no navegador em {time.monotonic() - t_lista:.1f}s: "
               + "; ".join(f"{p['url']} ({p['itens']} itens{', ' + p['erro'] if p.get('erro') else ''})"
                           for p in saida["paginas"]))
    evento("navegador", f"navegador terminou em {time.monotonic() - inicio:.1f}s")
    return saida


if __name__ == "__main__":
    modo = sys.argv[1]
    if modo == "home":
        resultado = _processo_home(sys.argv[2], sys.argv[3])
    else:
        resultado = _processo_listas(sys.argv[2], sys.argv[3:])
    print("NAVEGADOR " + json.dumps(resultado, ensure_ascii=False), flush=True)

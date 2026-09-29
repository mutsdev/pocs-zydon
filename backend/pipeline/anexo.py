"""Catálogo do cliente enviado como anexo (PDF, planilha ou Word).

Cada produto sai do próprio documento: nome e preço lidos no texto, imagem
recortada do arquivo. A imagem sobe para a Zydon (resource-files da org pocs),
porque o validar_poc exige temp_image_url http; o file_id vai junto para a URL
assinada (~2h) ser renovada na criação do portal. Nada vem do modelo.
"""

import base64
import csv
import io
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import selecao

PRECO = re.compile(r"R\$\s*([\d.]+,\d{2}|\d+(?:\.\d{2})?)")
COLUNAS = {
    "nome": ("nome", "produto", "descricao", "descrição", "item", "titulo", "título"),
    "preco": ("preco", "preço", "valor", "price", "pvenda", "preco venda", "preço de venda"),
    "categoria": ("categoria", "grupo", "linha", "familia", "família", "departamento"),
    "imagem": ("imagem", "foto", "image", "url imagem", "link imagem", "img"),
    "sku": ("sku", "codigo", "código", "cod", "referencia", "referência", "ref"),
}


def miniatura(conteudo, lado=160):
    """Data-URI JPEG pequena: a URL assinada da Zydon expira em ~2h, a miniatura não."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(conteudo)).convert("RGB")
        img.thumbnail((lado, lado))
        saida = io.BytesIO()
        img.save(saida, "JPEG", quality=78)
        return "data:image/jpeg;base64," + base64.b64encode(saida.getvalue()).decode()
    except Exception:
        return None


def fonte_do_anexo(nome):
    ext = Path(nome or "").suffix.lower()
    if ext in (".xlsx", ".xls", ".csv"):
        return "planilha"
    if ext == ".docx":
        return "documento"
    return "pdf"


def _preco(texto):
    m = PRECO.search(texto or "")
    if not m:
        return None
    bruto = m.group(1)
    valor = bruto.replace(".", "").replace(",", ".") if "," in bruto else bruto
    try:
        return round(float(valor), 2) or None
    except ValueError:
        return None


def _numero(valor):
    if isinstance(valor, (int, float)):
        return round(float(valor), 2) if valor > 0 else None
    texto = str(valor or "").strip()
    if not texto:
        return None
    return _preco(texto if "R$" in texto else f"R$ {texto}")


def _nome_do_bloco(texto):
    for linha in (texto or "").splitlines():
        linha = selecao.limpar_texto(PRECO.sub("", linha)).strip(" -–:|")
        if 4 <= len(linha) <= 110 and re.search(r"[A-Za-zÀ-ú]{3}", linha):
            return linha
    return ""


def _png(imagem_pil):
    imagem_pil = imagem_pil.convert("RGB")
    saida = io.BytesIO()
    imagem_pil.save(saida, "JPEG", quality=88)
    return saida.getvalue()


def ler_pdf(dados, nome_arquivo):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    documento = pdfium.PdfDocument(dados)
    itens = []
    for indice in range(min(len(documento), 40)):
        pagina = documento[indice]
        textos = pagina.get_textpage()
        secao = _nome_do_bloco(textos.get_text_bounded(0, pagina.get_height() - 90,
                                                         pagina.get_width(), pagina.get_height()))
        for obj in pagina.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=3):
            esq, base, dir_, topo = obj.get_bounds()
            if dir_ - esq < 50 or topo - base < 50:
                continue
            abaixo = textos.get_text_bounded(esq - 5, max(0, base - 60), dir_ + 100, base)
            ao_lado = textos.get_text_bounded(dir_, base, min(pagina.get_width(), dir_ + 260), topo)
            texto = abaixo if _nome_do_bloco(abaixo) else ao_lado
            nome = _nome_do_bloco(texto)
            try:
                figura = obj.get_bitmap(render=False).to_pil()
            except Exception:
                continue
            if figura.width < 120 or figura.height < 120:
                continue
            itens.append({"nome": nome, "preco": _preco(texto), "categoria": secao,
                          "imagem_bytes": _png(figura),
                          "origem_url": f"anexo:{nome_arquivo}#pagina={indice + 1}"})
    return itens


def _coluna(cabecalho, chave):
    nomes = [selecao.sem_acento(c) for c in cabecalho]
    for alvo in COLUNAS[chave]:
        alvo = selecao.sem_acento(alvo)
        for i, n in enumerate(nomes):
            if n == alvo:
                return i
    for alvo in COLUNAS[chave]:
        alvo = selecao.sem_acento(alvo)
        for i, n in enumerate(nomes):
            if alvo in n:
                return i
    return None


def _linhas_planilha(dados, nome_arquivo):
    ext = Path(nome_arquivo).suffix.lower()
    if ext == ".csv":
        texto = dados.decode("utf-8-sig", "ignore")
        dialeto = csv.Sniffer().sniff(texto[:2000], delimiters=";,\t") if texto else csv.excel
        return [list(l) for l in csv.reader(io.StringIO(texto), dialeto)], {}
    if ext == ".xls":
        import xlrd
        folha = xlrd.open_workbook(file_contents=dados).sheet_by_index(0)
        return [folha.row_values(i) for i in range(folha.nrows)], {}
    import openpyxl
    livro = openpyxl.load_workbook(io.BytesIO(dados), data_only=True)
    folha = livro.worksheets[0]
    imagens = {}
    for img in getattr(folha, "_images", []):
        try:
            linha = img.anchor._from.row
            imagens[linha] = img._data()
        except Exception:
            continue
    return [list(l) for l in folha.iter_rows(values_only=True)], imagens


def ler_planilha(dados, nome_arquivo):
    linhas, imagens = _linhas_planilha(dados, nome_arquivo)
    inicio = next((i for i, l in enumerate(linhas[:15])
                   if _coluna([str(c or "") for c in l], "nome") is not None), None)
    if inicio is None:
        return []
    cab = [str(c or "") for c in linhas[inicio]]
    col = {k: _coluna(cab, k) for k in COLUNAS}
    itens = []
    for n, linha in enumerate(linhas[inicio + 1:], start=inicio + 1):
        valor = lambda k: linha[col[k]] if col[k] is not None and col[k] < len(linha) else None
        nome = selecao.limpar_texto(valor("nome"))
        if not nome:
            continue
        item = {"nome": nome[:110], "preco": _numero(valor("preco")),
                "categoria": selecao.limpar_texto(valor("categoria")),
                "origem_url": f"anexo:{nome_arquivo}#linha={n + 1}"}
        url = str(valor("imagem") or "").strip()
        if url.startswith(("http://", "https://")):
            item["imagem_url"] = url
        elif n in imagens:
            item["imagem_bytes"] = imagens[n]
        itens.append(item)
    return itens


def ler_docx(dados, nome_arquivo):
    import docx
    documento = docx.Document(io.BytesIO(dados))
    itens = []
    for t, tabela in enumerate(documento.tables):
        linhas = [[c.text for c in r.cells] for r in tabela.rows]
        if not linhas:
            continue
        col = {k: _coluna(linhas[0], k) for k in COLUNAS}
        if col["nome"] is None:
            continue
        for n, (linha, row) in enumerate(zip(linhas[1:], tabela.rows[1:]), start=2):
            nome = selecao.limpar_texto(linha[col["nome"]])
            if not nome:
                continue
            imagem = None
            for blip in row._tr.xpath(".//a:blip"):
                rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                parte = documento.part.related_parts.get(rid)
                if parte is not None:
                    imagem = parte.blob
                    break
            itens.append({"nome": nome[:110],
                          "preco": _numero(linha[col["preco"]]) if col["preco"] is not None else None,
                          "categoria": selecao.limpar_texto(linha[col["categoria"]]) if col["categoria"] is not None else "",
                          "imagem_bytes": imagem,
                          "origem_url": f"anexo:{nome_arquivo}#tabela={t + 1}&linha={n}"})
    if itens:
        return itens
    pendente = None
    for p, par in enumerate(documento.paragraphs):
        blips = par._p.xpath(".//a:blip")
        if blips:
            rid = blips[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            parte = documento.part.related_parts.get(rid)
            pendente = parte.blob if parte is not None else None
            continue
        nome = _nome_do_bloco(par.text)
        if pendente and nome:
            itens.append({"nome": nome, "preco": _preco(par.text), "categoria": "",
                          "imagem_bytes": pendente,
                          "origem_url": f"anexo:{nome_arquivo}#paragrafo={p + 1}"})
            pendente = None
    return itens


def ler(nome_arquivo, conteudo_base64):
    dados = base64.b64decode(conteudo_base64)
    fonte = fonte_do_anexo(nome_arquivo)
    if fonte == "planilha":
        itens = ler_planilha(dados, nome_arquivo)
    elif fonte == "documento":
        itens = ler_docx(dados, nome_arquivo)
    else:
        itens = ler_pdf(dados, nome_arquivo)
    return fonte, itens


class Hospedagem:
    """Sobe imagem para resource-files da org e devolve (file_id, url assinada)."""

    def __init__(self, org="pocs"):
        import credenciais
        import portal
        self.portal = portal
        self.headers, dados_org = credenciais.carregar(org)
        codigo = self.headers["X-Zydon-Access-Key-Code"]
        token = self.headers["X-Zydon-Access-Key-Token"]
        self.jwt = portal.entrar(codigo, token, dados_org["portal_origem_id"])

    def subir(self, conteudo, nome):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / nome
            caminho.write_bytes(conteudo)
            file_id = self.portal.subir_arquivo(self.headers, caminho, "image/jpeg")
        url, _ = self.portal.url_do_arquivo(self.jwt, file_id)
        return file_id, url

    def renovar(self, file_id):
        return self.portal.url_do_arquivo(self.jwt, file_id)[0]


def candidatos_do_anexo(nome_arquivo, conteudo_base64, limite=60):
    """(fonte, candidatos, descartes). Candidato sem nome ou sem imagem é descartado com motivo."""
    fonte, itens = ler(nome_arquivo, conteudo_base64)
    selecao.evento("extracao", f"anexo {nome_arquivo}: {len(itens)} itens lidos ({fonte})")
    descartes, prontos = [], []
    for item in itens:
        if not item.get("nome") or not selecao.nome_valido(item["nome"], "anexo/x"):
            descartes.append({"nome": item.get("nome") or "(sem nome)", "motivo": "anexo: item sem nome de produto legível"})
        elif not item.get("imagem_bytes") and not item.get("imagem_url"):
            descartes.append({"nome": item["nome"], "motivo": "anexo: produto sem imagem no documento"})
        else:
            prontos.append(item)
    prontos = prontos[:limite]
    hospedagem = Hospedagem() if any(i.get("imagem_bytes") for i in prontos) else None

    def preparar(par):
        n, item = par
        if item.get("imagem_url"):
            return item, None, item["imagem_url"]
        try:
            file_id, url = hospedagem.subir(item["imagem_bytes"], f"anexo-{n:03d}.jpg")
            return item, file_id, url
        except Exception as erro:
            return item, None, f"erro: {type(erro).__name__}: {erro}"[:160]

    with ThreadPoolExecutor(6) as pool:
        preparados = list(pool.map(preparar, enumerate(prontos)))
    candidatos = []
    for item, file_id, url in preparados:
        if not str(url).startswith("http"):
            descartes.append({"nome": item["nome"], "motivo": f"anexo: imagem não subiu ({url})"})
            continue
        c = selecao.candidato(item["nome"], item["origem_url"], url, item.get("preco"),
                              item.get("categoria"), "", "anexo")
        if file_id:
            c["file_id"] = file_id
        if item.get("imagem_bytes"):
            c["miniatura"] = miniatura(item["imagem_bytes"])
        candidatos.append(c)
    selecao.evento("extracao", f"anexo: {len(candidatos)} produtos com imagem, {len(descartes)} descartados")
    return fonte, candidatos, descartes

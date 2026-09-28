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
        return json.loads((Path(pasta) / "paleta.json").read_text(encoding="utf-8")).get("principal")
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
    return "distribuição B2B", "nenhum sinal de ramo no site; valor padrão"


def conferir_logo(logo):
    """(logo_utilizavel, observacao). SVG que nao rasteriza nao passa calado."""
    if not logo or not str(logo).lower().endswith(".svg"):
        return logo, None
    try:
        import logo as mod_logo
        mod_logo._rasterizar_svg(logo)
        return logo, None
    except Exception as erro:
        return None, (f"a logo SVG do site não foi usada ({type(erro).__name__}: {erro}); "
                      f"os banners caem no fallback sem logo")


def extrair(entrada):
    import atendimento
    import extracao
    pedido_id = entrada["pedido_id"]
    pedido = {"pedido_id": pedido_id, "cliente": entrada["cliente"],
              "site": entrada["site"], "segmento": entrada.get("segmento") or ""}
    evento("extracao", f"lendo {entrada['site']}")
    dados = extracao._site_data(pedido["site"], pedido)
    evento("extracao", f"{len(dados['products'])} produtos com imagem válida")
    catalogo, resumo, logo_url = extracao._build_catalog(pedido, dados)

    requisicoes = next(e for e in catalogo["etapas"] if e.get("endpoint") == "products")["requests"]
    brutos = dados["products"][:len(requisicoes)]
    precos = []
    for req, bruto in zip(requisicoes, brutos):
        publico = isinstance(bruto.get("price"), (int, float)) and bruto["price"] > 0
        precos.append({"sku": req["payload"]["sku"], "nome": req["payload"]["name"],
                       "preco": req["payload"]["price"],
                       "origem": "publico" if publico else "estimado",
                       "fonte": "busca" if bruto.get("source_note") else "site"})
    observacoes = [resumo.get("observacoes") or ""]
    if not precos:
        situacao = "ausente"
    elif all(p["origem"] == "publico" for p in precos):
        situacao = "publico"
    else:
        situacao = "estimado"
    if situacao != resumo.get("preco"):
        observacoes.append(f"preço do resumo corrigido de '{resumo.get('preco')}' para "
                           f"'{situacao}' para bater com o catálogo")
    fonte = "busca" if any(p["fonte"] == "busca" for p in precos) else "site"

    segmento, origem = entrada.get("segmento"), "informado"
    criterio = None
    if not str(segmento or "").strip():
        texto = " ".join([dados.get("title", ""), dados.get("description", ""),
                          " ".join(p["nome"] for p in precos)])
        segmento, criterio = inferir_segmento(texto)
        origem = "inferido"
        evento("extracao", f"segmento inferido: {segmento} ({criterio})")

    caminho = gravar_catalogo(catalogo, pedido_id)
    valido, saida = atendimento.validar(caminho)
    if not valido:
        raise RuntimeError("catálogo reprovado no validar_poc.py: " + saida[-1500:])
    evento("extracao", "validar_poc.py: 0 erros")

    pasta = pasta_pedido(pedido_id)
    logo = atendimento.baixar_logo(logo_url, atendimento.prefixo(caminho.name)) if logo_url else None
    logo, aviso_logo = conferir_logo(logo)
    if aviso_logo:
        observacoes.append(aviso_logo)
        evento("extracao", aviso_logo, "aviso")
    if not logo_url:
        observacoes.append("nenhuma logo identificável foi encontrada no site")

    resumo = dict(resumo, preco=situacao, fonte=fonte, precos=precos,
                  executivo=entrada.get("executivo"), segmento=segmento,
                  segmento_origem=origem, segmento_criterio=criterio,
                  observacoes=" ".join(o for o in observacoes if o).strip())
    saida = {"catalogo": catalogo, "resumo": resumo, "logo_url": logo_url,
             "segmento": segmento, "segmento_origem": origem}
    if logo:
        saida["logo"] = {"nome": Path(logo).name,
                         "conteudo_base64": base64.b64encode(Path(logo).read_bytes()).decode()}
    return saida


def previa(entrada):
    import atendimento
    pedido_id = entrada["pedido_id"]
    pasta = pasta_pedido(pedido_id)
    logo = restaurar_logo(entrada, pasta)
    if not logo:
        return {"sem_banner": "sem logo: não há de onde tirar a paleta nem a marca"}
    caminho = gravar_catalogo(entrada["catalogo"], pedido_id)
    evento("banners", "gerando as peças (login e cabeçalho)")
    gerada, saida = atendimento.gerar_pecas(caminho, logo, entrada["cliente"],
                                            entrada.get("segmento"), candidatas=2)
    if not gerada:
        return {"sem_banner": str(saida)[-800:]}
    return {"pecas": pecas_para_tela(gerada), "cor": cor_da_pasta(gerada),
            "banners_tar": empacotar(gerada), "gerador": str(saida)[-1500:]}


def criar(entrada):
    import atendimento
    pedido_id = entrada["pedido_id"]
    pasta = pasta_pedido(pedido_id)
    logo = restaurar_logo(entrada, pasta)
    banners = restaurar_banners(entrada, pasta)
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
        nova, saida = atendimento.regerar_pecas(banners, pecas, candidatas=2,
                                                feedback=entrada.get("feedback"),
                                                cor=entrada.get("cor"))
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


ACOES = {"extrair": extrair, "previa": previa, "criar": criar, "banner": banner}


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

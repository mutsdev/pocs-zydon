"""Checagem estática do driver.py antes de publicar.
Toda ação que gera ou publica banner precisa estar em ACOES_COM_BANNER; senão a peça mobile
não é registrada e some da curadoria e do portal (caso da Galzerano)."""
import ast
import sys
from pathlib import Path

arvore = ast.parse(Path(__file__).resolve().parent.parent.joinpath("pipeline", "driver.py").read_text(encoding="utf-8"))
funcoes = {n.name: n for n in arvore.body if isinstance(n, ast.FunctionDef)}
GERA_BANNER = {"gerar_com_identidade", "_mobile_seguro", "peca_mobile", "publicar_pecas", "aplicar_pecas"}


def chamadas(no):
    for filho in ast.walk(no):
        if isinstance(filho, ast.Call):
            alvo = filho.func
            yield alvo.id if isinstance(alvo, ast.Name) else alvo.attr if isinstance(alvo, ast.Attribute) else None


def mexe_em_banner(nome, vistos=None):
    vistos = vistos if vistos is not None else set()
    if nome in vistos or nome not in funcoes:
        return False
    vistos.add(nome)
    return any(c in GERA_BANNER or mexe_em_banner(c, vistos) for c in chamadas(funcoes[nome]) if c)


def literal(nome):
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(isinstance(t, ast.Name) and t.id == nome for t in no.targets):
            return no.value
    raise SystemExit(f"{nome} não encontrado no driver.py")


acoes = {k.value: v.id for k, v in zip(literal("ACOES").keys, literal("ACOES").values)}
com_banner = {e.value for e in literal("ACOES_COM_BANNER").elts}
faltando = sorted(a for a, f in acoes.items() if mexe_em_banner(f) and a not in com_banner)
if faltando:
    print("ações que geram banner fora de ACOES_COM_BANNER (o mobile some):", ", ".join(faltando))
    sys.exit(1)
print(f"checagem ok: {len(com_banner)} ações com banner registram o mobile")

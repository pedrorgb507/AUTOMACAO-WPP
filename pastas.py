# -*- coding: utf-8 -*-
"""
Funcoes de pasta usadas pelas duas automacoes (WhatsApp e Teams):
montar a pasta do dia do cliente e arrumar nome de arquivo.

Mesma logica do VIGIA SOLIDA: reaproveita pasta que ja existe mesmo escrita
com acento ou caixa diferente, e nunca sobrescreve arquivo.
"""

import os
import re
import time


MESES = ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO",
         "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]

MESES_ACENTUADOS = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
                    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]

PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def montar_subpasta(cfg, quando):
    """Caminho relativo do dia. Fichas: {MES} {Mes} {mes} {dia} {ano} {data}."""
    modelo = cfg.get("subpasta_por_data") or "{MES}\\{dia}"
    nome_mes = (MESES_ACENTUADOS if cfg.get("mes_com_acento") else MESES)[quando.month - 1]
    fichas = {
        "MES": nome_mes,
        "Mes": nome_mes.capitalize(),
        "mes": "{:02d}".format(quando.month),
        "dia": "{:02d}".format(quando.day),
        "ano": "{}".format(quando.year),
        "data": quando.strftime(cfg.get("formato_pasta_dia", "%d-%m-%Y")),
    }
    caminho = modelo
    for ficha, valor in fichas.items():
        caminho = caminho.replace("{" + ficha + "}", valor)
    return caminho


def normalizar(texto):
    tabela = str.maketrans("ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ", "AAAAAEEEEIIIIOOOOOUUUUC")
    return re.sub(r"\s+", " ", texto.upper().translate(tabela)).strip()


def achar_pasta_existente(pai, nome_desejado):
    """Reaproveita uma pasta equivalente que ja exista (maiuscula/minuscula, acento)."""
    if not os.path.isdir(pai):
        return nome_desejado
    alvo = normalizar(nome_desejado)
    try:
        for existente in os.listdir(pai):
            if os.path.isdir(os.path.join(pai, existente)) and normalizar(existente) == alvo:
                return existente
    except OSError:
        pass
    return nome_desejado


def pasta_do_dia(cfg, quando, pasta_base=None, avisar=None):
    """Monta (e cria) a pasta do dia dentro de pasta_base."""
    base = pasta_base or cfg["pasta_base"]
    raiz = os.path.dirname(base.rstrip("\\/")) or base
    if not os.path.isdir(base) and avisar:
        avisar("AVISO: pasta base nao existia, criando: {}".format(base))
    del raiz
    caminho = base
    for parte in montar_subpasta(cfg, quando).replace("/", "\\").split("\\"):
        if parte:
            caminho = os.path.join(caminho, achar_pasta_existente(caminho, parte))
    os.makedirs(caminho, exist_ok=True)
    return caminho


def pasta_do_dia_do_cliente(cfg, pasta_trabalho, nome_cliente, quando, avisar=None):
    """Pasta do dia de um cliente dentro da pasta de trabalho (\\\\servidor\\TRABALHO)."""
    if not os.path.isdir(pasta_trabalho):
        raise OSError("pasta de trabalho inacessivel: {}".format(pasta_trabalho))
    achado = achar_pasta_existente(pasta_trabalho, nome_cliente)
    base = os.path.join(pasta_trabalho, achado)
    if not os.path.isdir(base) and avisar:
        avisar("AVISO: pasta do cliente nao existia, criando: {}".format(base))
    return pasta_do_dia(cfg, quando, pasta_base=base, avisar=avisar)


def nome_seguro(nome):
    nome = PROIBIDOS.sub("_", nome or "").strip().rstrip(". ")
    return nome[:180] or "arquivo"


def nome_livre(pasta, nome_arquivo):
    destino = os.path.join(pasta, nome_arquivo)
    if not os.path.exists(destino):
        return destino
    base, ext = os.path.splitext(nome_arquivo)
    for n in range(2, 1000):
        tentativa = os.path.join(pasta, "{}_{}{}".format(base, n, ext))
        if not os.path.exists(tentativa):
            return tentativa
    return os.path.join(pasta, "{}_{}{}".format(base, int(time.time()), ext))


def gravar_arquivo(pasta, nome, dados):
    """Grava primeiro como .parte e so depois renomeia, para ninguem pegar arquivo pela metade."""
    destino = nome_livre(pasta, nome_seguro(nome))
    with open(destino + ".parte", "wb") as f:
        f.write(dados)
    os.replace(destino + ".parte", destino)
    return destino

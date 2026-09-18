# -*- coding: utf-8 -*-
"""Desenho dos avisos na tela dos robos.

Os robos rodam lado a lado em terminais do VS Code e cada um escrevia no seu
proprio formato. Quem passa os olhos precisa achar tres coisas sem ler linha
por linha: de que cliente e o arquivo, se ele foi baixado e se foi marcado.
Por isso todo evento que importa sai como um bloco fechado, igual nos quatro.

O bloco vai limpo para a tela e carimbado com a hora para o arquivo de log.
Sao publicos diferentes: na tela o carimbo repetido em toda linha atrapalha a
leitura, e no log ele e justamente o que permite reconstruir o dia depois.
"""

import datetime as dt

LARGURA = 60


def _imprimir(texto):
    # O terminal do Windows nem sempre aceita acento; perder a linha inteira
    # por causa de um caractere seria pior do que mostra-la trocada.
    try:
        print(texto, flush=True)
    except UnicodeEncodeError:
        print(texto.encode("ascii", "replace").decode(), flush=True)


def _gravar(caminho_log, linhas):
    if not caminho_log:
        return
    carimbo = dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    try:
        with open(caminho_log, "a", encoding="utf-8") as f:
            for linha in linhas:
                f.write("[{}] {}\n".format(carimbo, linha))
    except OSError:
        # Log e registro, nao operacao: se a gravacao falhar o robo segue.
        pass


def bloco(caminho_log, cliente, itens):
    """Escreve um bloco do painel.

    'itens' e uma lista de (rotulo, valor), na ordem em que deve aparecer:

        valor None  -> a linha nao sai. Use quando o robo NAO SABE o resultado;
                       inventar um "OK" aqui e o erro que este projeto ja pagou
                       caro tres vezes.
        valor ""    -> sai so o rotulo, sem dois-pontos (ex.: "URGENTE !!").
        valor texto -> sai "ROTULO: texto".
    """
    traco = "-" * LARGURA
    linhas = ["CLIENTE - {}".format(cliente)]
    for rotulo, valor in itens:
        if valor is None:
            continue
        linhas.append(rotulo if valor == "" else "{}: {}".format(rotulo, valor))

    _imprimir(traco)
    for linha in linhas:
        _imprimir(linha)
    _imprimir(traco)
    # Linha vazia no fim: sem ela dois blocos seguidos colam um tracejado no
    # outro e a tela vira uma parede de tracos.
    _imprimir("")
    _gravar(caminho_log, linhas)


def ok_ou(falhou, resultado):
    """Traduz um resultado de tres estados para o texto do painel.

    True -> 'OK'; False -> o texto de falha; None -> None, que apaga a linha.
    'Nao sei' nunca pode virar 'nao', porque marcar de novo o que ja estava
    marcado REMOVE o visto no Teams e no WhatsApp.
    """
    if resultado is None:
        return None
    return "OK" if resultado else falhou

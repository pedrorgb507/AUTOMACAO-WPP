# -*- coding: utf-8 -*-
"""Sobe o vigia do Teams e o do CIP num processo so, dividindo UM navegador.

Os dois atendem a Solida pela mesma conta: um baixa o que ela manda e marca a
mensagem, o outro devolve os .ppf do CTP. Antes eram dois processos separados;
hoje nao podem ser, porque o perfil do Chrome (perfil_teams_web) nao aceita
dois donos ao mesmo tempo - o segundo a subir simplesmente nao abre.

Entao aqui abre-se uma janela e empresta-se aos dois, em ordem, a cada rodada.
A pagina e recarregada a cada volta: reaproveitar a mesma por horas fez o
clique no anexo parar de abrir a aba do OneDrive, e o robo via o arquivo sem
baixar. Recarregar custa poucos segundos; reabrir o Chrome custa dezenas.

Fechar a janela do terminal derruba os dois.

Uso:
    python vigiar_teams_e_cip.py
"""

import datetime as dt
import sys
import time

import teams_web as tw
import vigia_cip as cip


def registrar(msg):
    linha = "[{}] [GERAL] {}".format(dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"), msg)
    try:
        print(linha, flush=True)
    except UnicodeEncodeError:
        print(linha.encode("ascii", "replace").decode(), flush=True)


def uma_rodada(cfg_web, cfg_cip, sessao, primeira):
    """Baixa o que chegou e manda o que esta na fila, na mesma janela."""
    if primeira:
        sessao.pagina()
    else:
        sessao.recarregar()
    tw.passada_na_pagina(cfg_web, sessao.contexto(), sessao.pagina())
    cip.uma_passada(cfg_cip, sessao=sessao)


def main():
    cfg_web = tw.ler_config()
    cfg_cip = cip.ler_config()
    intervalo = int(cfg_web.get("segundos_entre_checagens", 60))
    registrar("Vigiando a Solida (baixar + devolver .ppf) a cada {}s.".format(intervalo))
    registrar("Feche esta janela para parar os dois.")

    sessao = tw.SessaoNavegador(visivel=bool(cfg_web.get("mostrar_navegador", False)))
    primeira = True
    try:
        while True:
            try:
                uma_rodada(cfg_web, cfg_cip, sessao, primeira)
                primeira = False
            except KeyboardInterrupt:
                registrar("Encerrado pelo usuario.")
                return
            except Exception as e:
                registrar("ERRO inesperado: {}".format(str(e)[:150]))
                # a janela pode ter morrido junto: joga fora e abre outra
                sessao.fechar()
                primeira = True
            try:
                time.sleep(intervalo)
            except KeyboardInterrupt:
                registrar("Encerrado pelo usuario.")
                return
            # reler os configs deixa mudar pasta, cliente e intervalo sem
            # derrubar o vigia
            try:
                cfg_web = tw.ler_config()
                cfg_cip = cip.ler_config()
                intervalo = int(cfg_web.get("segundos_entre_checagens", 60))
            except (SystemExit, ValueError, OSError):
                pass
    finally:
        sessao.fechar()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

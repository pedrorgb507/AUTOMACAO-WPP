# -*- coding: utf-8 -*-
"""
REENVIAR AVISO - manda de novo no chat do Teams o aviso de arquivos que o
vigia ja salvou (anexo + link que abre sem login), sem baixar nada de novo.

Uso:
    python reenviar_aviso.py "arquivo1.pdf" "arquivo2.pdf"
    python reenviar_aviso.py --data 14/09/2026 "arquivo.pdf"

Procura cada arquivo na pasta do dia (hoje, ou a data informada) do
config_teams.json.
"""

import argparse
import datetime as dt
import os
import sys
import urllib.parse

import pastas
import vigia_teams as v


def main():
    p = argparse.ArgumentParser(description="Reenvia o aviso de arquivos ja salvos para o chat.")
    p.add_argument("arquivos", nargs="+", help="nomes dos arquivos (como aparecem na pasta do dia)")
    p.add_argument("--data", help="dia da pasta, dd/mm/aaaa (padrao: hoje)")
    args = p.parse_args()

    cfg = v.ler_config()
    quando = dt.datetime.strptime(args.data, "%d/%m/%Y") if args.data else dt.datetime.now()
    pasta = pastas.pasta_do_dia(cfg, quando, avisar=v.registrar)

    base_sp = cfg.get("link_base_sharepoint") or \
        "https://finartdigital.sharepoint.com/sites/FinartDigital/Documentos Compartilhados/SOLIDA GRAFICA/"

    lista = []
    for nome in args.arquivos:
        caminho = os.path.join(pasta, nome)
        if not os.path.isfile(caminho):
            v.registrar("ERRO: nao achei '{}' em {}".format(nome, pasta))
            continue
        lista.append((nome, caminho, base_sp + nome))

    if not lista:
        v.registrar("Nada para reenviar.")
        sys.exit(1)

    token = v.obter_token(cfg)
    if not token:
        sys.exit(1)
    v.registrar("REENVIANDO aviso de {} arquivo(s) para o chat...".format(len(lista)))
    ok = v.avisar_no_chat(token, cfg, lista)
    v.registrar("Reenvio concluido." if ok else "Reenvio FALHOU - veja os avisos acima.")


if __name__ == "__main__":
    main()

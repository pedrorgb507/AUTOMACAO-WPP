# -*- coding: utf-8 -*-
"""Guarda os arquivos de configuracao no servidor.

Os configs sao os unicos arquivos deste projeto que NAO vao para o GitHub: eles
trazem telefone de cliente, a senha de app do Gmail e o nome dos grupos, e o
repositorio e publico. Sem esta copia eles existiriam num disco so - e a lista
de clientes, que levou meses para ser montada, morre junto com o HD.

Uso:
    python guardar_configs.py           guarda o que mudou
    python guardar_configs.py --listar  mostra o que ja esta guardado
"""

import argparse
import datetime as dt
import os
import shutil
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DESTINO = r"\\servidor\Finart\CONFIGS GUARDADOS"
HISTORICO = os.path.join(DESTINO, "historico")

# Só os arquivos que sao trabalhosos de refazer. Os tokens do Drive e o perfil
# do navegador ficam de fora de proposito: sao recriados entrando na conta de
# novo, e espalhar credencial por pasta de rede aumenta a superficie sem
# necessidade.
ARQUIVOS = [
    "config.json",
    "config_cip.json",
    "config_email.json",
    "config_teams_web.json",
]

# Quantas versoes antigas manter de cada arquivo.
VERSOES = 20


def registrar(msg):
    print("[{}] {}".format(dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"), msg), flush=True)


def iguais(a, b):
    """True quando os dois arquivos tem exatamente o mesmo conteudo."""
    try:
        with open(a, "rb") as f1, open(b, "rb") as f2:
            return f1.read() == f2.read()
    except OSError:
        return False


def podar(nome):
    """Deixa so as VERSOES copias mais novas deste arquivo no historico."""
    base = os.path.splitext(nome)[0]
    try:
        antigas = sorted(x for x in os.listdir(HISTORICO) if x.endswith("_" + nome))
    except OSError:
        return
    for velha in antigas[:-VERSOES]:
        try:
            os.remove(os.path.join(HISTORICO, velha))
        except OSError:
            pass


def guardar():
    try:
        os.makedirs(HISTORICO, exist_ok=True)
    except OSError as e:
        registrar("ERRO: nao consegui chegar em {} ({}).".format(DESTINO, e))
        return 1

    carimbo = dt.datetime.now().strftime("%Y-%m-%d_%H-%M")
    mudou = 0
    for nome in ARQUIVOS:
        origem = os.path.join(AQUI, nome)
        if not os.path.exists(origem):
            continue
        copia = os.path.join(DESTINO, nome)

        if os.path.exists(copia) and iguais(origem, copia):
            continue

        # O historico vem PRIMEIRO. Se a copia de cima fosse escrita antes e o
        # config estivesse corrompido, o bom seria sobrescrito e nao haveria a
        # que voltar - que e como um backup vira uma falsa sensacao de seguranca.
        try:
            shutil.copy2(origem, os.path.join(HISTORICO, "{}_{}".format(carimbo, nome)))
            shutil.copy2(origem, copia)
        except OSError as e:
            registrar("ERRO ao guardar {}: {}".format(nome, e))
            continue
        podar(nome)
        registrar("guardado: {}".format(nome))
        mudou += 1

    if mudou:
        registrar("{} arquivo(s) atualizado(s) em {}".format(mudou, DESTINO))
    else:
        registrar("nada mudou; as copias ja estavam em dia.")
    return 0


def listar():
    if not os.path.isdir(DESTINO):
        registrar("A pasta {} nao esta acessivel.".format(DESTINO))
        return 1
    print("\nCopia mais recente (e a que se usa para restaurar):")
    for nome in ARQUIVOS:
        c = os.path.join(DESTINO, nome)
        if os.path.exists(c):
            quando = dt.datetime.fromtimestamp(os.path.getmtime(c))
            print("   {:<26} {}".format(nome, quando.strftime("%d/%m/%Y %H:%M")))
        else:
            print("   {:<26} AINDA NAO GUARDADO".format(nome))
    try:
        h = sorted(os.listdir(HISTORICO))
    except OSError:
        h = []
    print("\nHistorico: {} versao(oes) guardada(s).".format(len(h)))
    for x in h[-5:]:
        print("   " + x)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Guarda os configs no servidor.")
    ap.add_argument("--listar", action="store_true", help="mostra o que ja esta guardado")
    a = ap.parse_args()
    sys.exit(listar() if a.listar else guardar())


if __name__ == "__main__":
    main()

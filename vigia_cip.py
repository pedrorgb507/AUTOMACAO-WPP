# -*- coding: utf-8 -*-
"""
VIGIA CIP - vigia a pasta do CTP da Solida, renomeia o .ppf para o numero da OS,
manda o arquivo como anexo no chat externo da Solida e arquiva em ENVIADOS.

Fluxo de cada arquivo:
    1. espera o arquivo parar de crescer (o CTP ainda pode estar gravando)
    2. renomeia tirando o prefixo do formato:
       "775X635 - ABS 175 LPI_49862R1__.ppf"  ->  "49862R1__.ppf"
    3. sobe para o OneDrive, libera leitura para o cliente e posta como anexo
       no chat do Teams (sem liberar, o cliente cai em "Voce precisa de acesso")
    4. move para a subpasta ENVIADOS

Usa cache de token proprio (token_cip.bin) porque precisa de Files.ReadWrite,
escopo que o vigia_teams.py nao tem. Assim os dois logins ficam independentes
e mexer aqui nao derruba o vigia do Teams que esta em producao.

Uso:
    python vigia_cip.py            uma passada
    python vigia_cip.py --vigiar   fica rodando
    python vigia_cip.py --teste    mostra o que faria, sem enviar nem mover
    python vigia_cip.py --login    forca novo login (primeira vez)
    python vigia_cip.py --reenviar "49888__.ppf" "49891__.ppf"
                                   manda de novo arquivos que ja estao em ENVIADOS
"""

import argparse
import base64
import datetime as dt
import json
import os
import sys
import time
import urllib.parse

try:
    import msal
    import requests
except ImportError:
    print("Faltam bibliotecas. Rode INSTALAR-BIBLIOTECAS.bat ou:")
    print("    pip install msal requests")
    sys.exit(1)

import graph_anexo
import pastas


AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config_cip.json")
CACHE_TOKEN = os.path.join(AQUI, "token_cip.bin")
LOG = os.path.join(AQUI, "vigia_cip.log")

GRAPH = "https://graph.microsoft.com/v1.0"

# Files.ReadWrite e o que permite subir o arquivo para o OneDrive; sem ele o
# Teams so aceitaria link, nao anexo.
ESCOPOS = ["ChatMessage.Send", "Files.ReadWrite.All", "User.Read"]

class ErroGraph(Exception):
    def __init__(self, status, texto):
        super().__init__("HTTP {}: {}".format(status, texto[:300]))
        self.status = status


def registrar(msg):
    linha = "[{}] {}".format(dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"), msg)
    try:
        print(linha, flush=True)
    except UnicodeEncodeError:
        print(linha.encode("ascii", "replace").decode(), flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def ler_config():
    if not os.path.exists(CONFIG):
        registrar("ERRO: config_cip.json nao encontrado ao lado do script.")
        sys.exit(1)
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for campo in ("client_id", "tenant_id"):
        if not (cfg.get(campo) or "").strip():
            registrar("ERRO: preencha '{}' no config_cip.json.".format(campo))
            sys.exit(1)
    if not cfg.get("pastas"):
        registrar("ERRO: nenhuma pasta configurada em 'pastas' no config_cip.json.")
        sys.exit(1)
    for e in cfg["pastas"]:
        for campo in ("pasta", "chat_id", "destino"):
            if not (e.get(campo) or "").strip():
                registrar("ERRO: falta '{}' na pasta '{}' do config_cip.json.".format(
                    campo, e.get("nome") or "?"))
                sys.exit(1)
        if e["destino"] not in ("teams", "whatsapp"):
            registrar("ERRO: destino '{}' invalido em '{}'. Use 'teams' ou 'whatsapp'.".format(
                e["destino"], e.get("nome")))
            sys.exit(1)
    return cfg


def rotulo(entrada):
    return entrada.get("nome") or entrada.get("pasta")


# ----------------------------------------------------------------------
# login e API
# ----------------------------------------------------------------------

def obter_token(cfg, forcar_login=False):
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_TOKEN):
        try:
            cache.deserialize(open(CACHE_TOKEN, "r", encoding="utf-8").read())
        except (OSError, ValueError):
            pass
    app = msal.PublicClientApplication(
        cfg["client_id"],
        authority="https://login.microsoftonline.com/{}".format(cfg["tenant_id"]),
        token_cache=cache)

    resultado = None
    if not forcar_login:
        contas = app.get_accounts()
        if contas:
            resultado = app.acquire_token_silent(ESCOPOS, account=contas[0])
    if not resultado:
        if cfg.get("modo_login") == "codigo":
            fluxo = app.initiate_device_flow(scopes=ESCOPOS)
            registrar(fluxo.get("message", "Abra o link e digite o codigo."))
            resultado = app.acquire_token_by_device_flow(fluxo)
        else:
            resultado = app.acquire_token_interactive(scopes=ESCOPOS)

    if not resultado or "access_token" not in resultado:
        registrar("ERRO no login: {}".format((resultado or {}).get("error_description", "sem detalhe")))
        return None
    if cache.has_state_changed:
        try:
            with open(CACHE_TOKEN, "w", encoding="utf-8") as f:
                f.write(cache.serialize())
        except OSError:
            pass
    return resultado["access_token"]


def graph(token, metodo, url, **kwargs):
    if url.startswith("/"):
        url = GRAPH + url
    cabecalho = {"Authorization": "Bearer " + token}
    cabecalho.update(kwargs.pop("headers", {}))
    for _ in range(4):
        r = requests.request(metodo, url, headers=cabecalho, timeout=300, **kwargs)
        if r.status_code == 429 or r.status_code >= 500:
            espera = int(r.headers.get("Retry-After", 5))
            registrar("API ocupada ({}), esperando {}s.".format(r.status_code, espera))
            time.sleep(espera)
            continue
        if r.status_code >= 400:
            raise ErroGraph(r.status_code, r.text)
        return r
    raise ErroGraph(r.status_code, r.text)


# ----------------------------------------------------------------------
# nome do arquivo
# ----------------------------------------------------------------------

MARCA_FORMATO = " - ABS "


def nome_limpo(nome):
    """Tira o prefixo do formato, deixando so a parte da OS.

    "775X635 - ABS 175 LPI_49862R1__.ppf"  ->  "49862R1__.ppf"
    "510x400 - ABS 175 lpi_49651__.ppf"    ->  "49651__.ppf"

    O que vem depois do primeiro underscore volta inteiro: R1, underscores do
    fim e OS multiplas ("49830 49853__") fazem parte do nome que a Solida
    espera. Nome fora do padrao volta intacto - renomear no escuro seria pior
    do que deixar como esta.
    """
    base, ext = os.path.splitext(nome)
    pos = base.upper().find(MARCA_FORMATO)
    if pos < 0:
        return nome
    depois = base[pos + len(MARCA_FORMATO):]
    if "_" not in depois:
        return nome
    limpo = depois.split("_", 1)[1].strip()

    # o RIP as vezes repete o formato ("... - ABS 175 LPI_775x635_49894R1__"),
    # e tirar so o primeiro pedaco deixaria "775x635_49894R1__" chegando assim
    # no cliente. Vai descascando enquanto o inicio nao parecer numero de OS.
    tentativa = limpo
    while "_" in tentativa:
        cabeca, resto = tentativa.split("_", 1)
        if _comeca_com_os(cabeca) or not resto.strip():
            break
        tentativa = resto.strip()
    # so aceita o descascamento se ele parou num numero de OS. Sem essa trava,
    # um nome que nao tem OS nenhuma seria descascado ate nao sobrar nada.
    if _comeca_com_os(tentativa):
        limpo = tentativa

    return (limpo + ext) if limpo else nome


def _comeca_com_os(pedaco):
    """True se o pedaco comeca com numero de OS (4 digitos ou mais)."""
    digitos = ""
    for c in pedaco:
        if not c.isdigit():
            break
        digitos += c
    return len(digitos) >= 4


def arquivo_estavel(caminho, segundos):
    """True quando o arquivo parou de crescer.

    O CTP grava o .ppf aos poucos; mandar no meio da gravacao entregaria um
    arquivo truncado para o cliente.
    """
    try:
        antes = os.path.getsize(caminho)
    except OSError:
        return False
    time.sleep(segundos)
    try:
        return os.path.getsize(caminho) == antes
    except OSError:
        return False


# ----------------------------------------------------------------------
# envio
# ----------------------------------------------------------------------

def subir_para_onedrive(token, caminho, nome):
    """Sobe o arquivo e devolve o item do OneDrive."""
    return graph_anexo.subir(graph, token, caminho, nome)


def mandar_no_chat(token, entrada, item, nome):
    """Libera o arquivo para o cliente e posta com ele anexado no chat do Teams."""
    erros = (ErroGraph, requests.RequestException, KeyError, ValueError)
    emails = entrada.get("emails_chat") or []
    try:
        graph_anexo.liberar_para(graph, token, item, emails)
    except erros as e:
        registrar("AVISO: nao consegui liberar '{}' para {} ({}).".format(nome, emails, e))

    links_html = ""
    if entrada.get("link_publico_no_chat", False):
        try:
            link = graph_anexo.link_publico(graph, token, item)
            if link:
                links_html = '<p><a href="{}">{}</a></p>'.format(link, nome)
        except erros as e:
            registrar("AVISO: nao consegui criar link publico de '{}' ({}).".format(nome, e))

    corpo = graph_anexo.corpo_com_anexos([(nome, item)], (entrada.get("mensagem") or "").strip(), links_html)
    graph(token, "POST", "/chats/{}/messages".format(entrada["chat_id"]), json=corpo)


def mandar_no_whatsapp(entrada, caminho, nome):
    """Manda o arquivo como documento no WhatsApp, pelo OpenWA.

    Reaproveita o vigia do WhatsApp para achar a sessao e respeitar o limite de
    chamadas por segundo da API, em vez de duplicar essa conversa aqui.
    """
    import vigia_whatsapp as wa
    cfg_wa = wa.ler_config()
    chave = wa.ler_api_key(cfg_wa)
    sessao = wa.achar_sessao(cfg_wa, chave)
    if not sessao:
        raise RuntimeError("nenhuma sessao do WhatsApp conectada no OpenWA")
    with open(caminho, "rb") as f:
        dados = base64.b64encode(f.read()).decode("ascii")
    corpo = {
        "chatId": entrada["chat_id"],
        "base64": dados,
        # octet-stream porque .ppf nao tem tipo padrao; o WhatsApp mostra o
        # arquivo pelo nome de qualquer jeito
        "mimetype": "application/octet-stream",
        "filename": nome,
    }
    texto = (entrada.get("mensagem") or "").strip()
    if texto:
        corpo["caption"] = texto
    wa.chamar(cfg_wa, chave, "/api/sessions/{}/messages/send-document".format(
        urllib.parse.quote(sessao["id"], safe="")), metodo="POST", corpo=corpo, timeout=300)


def reenviar(cfg, nomes):
    """Manda de novo arquivos que ja estao em ENVIADOS, sem mover nada.

    Reaproveita o item que ja esta no OneDrive (nao duplica); so sobe de novo
    se ele nao existir mais.
    """
    token = obter_token(cfg)
    if not token:
        return 0
    # so as pastas que mandam para o Teams: reenviar no WhatsApp seria outro caminho
    entradas = [e for e in cfg["pastas"] if e["destino"] == "teams"]
    feitos = 0
    for nome in nomes:
        entrada, caminho = None, None
        for e in entradas:
            tentativa = os.path.join(e["pasta"], e.get("subpasta_enviados") or "ENVIADOS", nome)
            if os.path.isfile(tentativa):
                entrada, caminho = e, tentativa
                break
        if not entrada:
            entrada = entradas[0] if entradas else None
        if not entrada:
            registrar("ERRO: nenhuma pasta com destino 'teams' no config.")
            return feitos
        try:
            item = graph_anexo.item_existente(graph, token, nome)
            if not item:
                if not caminho:
                    registrar("ERRO: '{}' nao esta no OneDrive nem em nenhuma pasta ENVIADOS.".format(nome))
                    continue
                item = subir_para_onedrive(token, caminho, nome)
            mandar_no_chat(token, entrada, item, nome)
        except (ErroGraph, requests.RequestException, OSError) as e:
            registrar("ERRO ao reenviar '{}': {}".format(nome, e))
            continue
        registrar("REENVIADO  >>  {}".format(nome))
        feitos += 1
    return feitos


# ----------------------------------------------------------------------
# passada
# ----------------------------------------------------------------------

def arquivos_da_pasta(entrada):
    pasta = entrada["pasta"]
    if not os.path.isdir(pasta):
        return None
    aceitas = [e.lower() for e in (entrada.get("extensoes_aceitas") or [])]
    saida = []
    for nome in sorted(os.listdir(pasta)):
        caminho = os.path.join(pasta, nome)
        if not os.path.isfile(caminho):
            continue
        if nome.startswith("~") or nome.lower().endswith(".tmp"):
            continue
        if aceitas and os.path.splitext(nome)[1].lower() not in aceitas:
            continue
        saida.append((nome, caminho))
    return saida


ULTIMO_ESTADO = {}


def avisar_estado(chave, texto):
    """Registra so quando muda. A chave separa o estado de cada pasta, senao
    duas pastas ficariam se sobrescrevendo e repetindo aviso a cada passada."""
    if ULTIMO_ESTADO.get(chave) != texto:
        ULTIMO_ESTADO[chave] = texto
        registrar(texto)


def processar_pasta(cfg, entrada, token_teams, modo_teste):
    """Envia tudo que estiver na pasta dessa entrada. Devolve (feitos, token)."""
    nome_pasta = rotulo(entrada)

    # 'ativo': false pausa a pasta sem apagar a configuracao. Avisa uma vez a
    # cada mudanca de estado: pausa silenciosa e pausa esquecida.
    if not entrada.get("ativo", True):
        avisar_estado(nome_pasta, "PAUSADO: '{}' nao esta enviando (ativo=false no config_cip.json).".format(
            nome_pasta))
        return 0, token_teams

    arquivos = arquivos_da_pasta(entrada)
    if arquivos is None:
        avisar_estado(nome_pasta, "Pasta inacessivel: {}. Tento de novo.".format(entrada["pasta"]))
        return 0, token_teams
    if not arquivos:
        avisar_estado(nome_pasta, "Vigiando {}. Aguardando arquivos...".format(entrada["pasta"]))
        return 0, token_teams

    enviados_dir = os.path.join(entrada["pasta"], entrada.get("subpasta_enviados") or "ENVIADOS")
    espera = float(cfg.get("segundos_estabilidade", 5))
    renomeia = entrada.get("renomear", False)
    feitos = 0

    for nome, caminho in arquivos:
        novo_nome = nome_limpo(nome) if renomeia else nome
        if renomeia and MARCA_FORMATO not in nome.upper():
            registrar("AVISO: '{}' nao tem o prefixo de formato; mando com o nome como esta.".format(nome))

        if modo_teste:
            registrar("[TESTE] {} | {}".format(nome_pasta, nome))
            registrar("        iria como '{}' para o {} '{}', depois para ENVIADOS".format(
                novo_nome, entrada["destino"], entrada.get("nome_do_chat") or entrada["chat_id"]))
            continue

        if not arquivo_estavel(caminho, espera):
            registrar("'{}' ainda esta sendo gravado; deixo para a proxima passada.".format(nome))
            continue

        try:
            if entrada["destino"] == "teams":
                if not token_teams:
                    token_teams = obter_token(cfg)
                    if not token_teams:
                        return feitos, token_teams
                item = subir_para_onedrive(token_teams, caminho, novo_nome)
                mandar_no_chat(token_teams, entrada, item, novo_nome)
            else:
                mandar_no_whatsapp(entrada, caminho, novo_nome)
        except Exception as e:
            # nao move: sem envio confirmado o arquivo continua na fila
            registrar("ERRO ao mandar '{}' ({}): {}".format(novo_nome, nome_pasta, e))
            continue

        try:
            os.makedirs(enviados_dir, exist_ok=True)
            destino = pastas.nome_livre(enviados_dir, novo_nome)
            os.replace(caminho, destino)
        except OSError as e:
            # ja foi enviado: avisa alto, porque a proxima passada mandaria de novo
            registrar("ATENCAO: '{}' foi enviado mas NAO saiu da pasta ({}). "
                      "Mova na mao para nao mandar duas vezes.".format(novo_nome, e))
            continue

        registrar("ENVIADO  >>  {}  ({})".format(novo_nome, nome_pasta))
        if novo_nome != nome:
            registrar("    de: {}".format(nome))
        registrar("    arquivado em: {}".format(destino))
        feitos += 1
    return feitos, token_teams


def uma_passada(cfg, modo_teste=False):
    total = 0
    token = None  # so pede o login do Teams se alguma pasta precisar
    for entrada in cfg["pastas"]:
        try:
            feitos, token = processar_pasta(cfg, entrada, token, modo_teste)
            total += feitos
        except Exception as e:
            registrar("ERRO na pasta '{}': {}".format(rotulo(entrada), e))
    return total


def vigiar(cfg):
    intervalo = int(cfg.get("segundos_entre_checagens", 30))
    registrar("Vigiando {} pasta(s) a cada {}s: {}. Feche a janela para parar.".format(
        len(cfg["pastas"]), intervalo,
        ", ".join("{} -> {}".format(rotulo(e), e["destino"]) for e in cfg["pastas"])))
    while True:
        try:
            uma_passada(cfg)
        except KeyboardInterrupt:
            registrar("Encerrado pelo usuario.")
            return
        except Exception as e:
            registrar("ERRO inesperado: {}".format(e))
        try:
            time.sleep(intervalo)
        except KeyboardInterrupt:
            registrar("Encerrado pelo usuario.")
            return
        try:
            cfg = ler_config()
        except (SystemExit, ValueError, OSError):
            pass


def main():
    p = argparse.ArgumentParser(description="Vigia a pasta do CTP e manda os .ppf no chat da Solida.")
    p.add_argument("--vigiar", action="store_true", help="fica rodando")
    p.add_argument("--teste", action="store_true", help="mostra o que faria, sem enviar nem mover")
    p.add_argument("--login", action="store_true", help="forca um novo login")
    p.add_argument("--reenviar", nargs="+", metavar="ARQUIVO",
                   help="manda de novo arquivos que ja estao em ENVIADOS")
    args = p.parse_args()

    cfg = ler_config()
    if args.login:
        registrar("Login OK." if obter_token(cfg, forcar_login=True) else "Login falhou.")
        return
    if args.reenviar:
        n = reenviar(cfg, args.reenviar)
        registrar("{} arquivo(s) reenviado(s).".format(n))
        return
    if args.vigiar:
        vigiar(cfg)
    else:
        n = uma_passada(cfg, modo_teste=args.teste)
        if not args.teste:
            registrar("{} arquivo(s) enviado(s).".format(n))


if __name__ == "__main__":
    main()

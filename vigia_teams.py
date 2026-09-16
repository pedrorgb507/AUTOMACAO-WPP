# -*- coding: utf-8 -*-
"""
VIGIA TEAMS - baixa os arquivos postados no canal do Teams e salva na pasta
do dia do cliente. Depois de salvar, marca a mensagem com um visto (✅) e,
se configurado, manda o nome e o link do arquivo num chat do Teams.

Conversa com a Microsoft pela API Graph, usando a SUA conta (login uma vez
so; depois o token se renova sozinho).

Uso:
    python vigia_teams.py             uma passada
    python vigia_teams.py --vigiar    fica rodando e checa a cada N segundos
    python vigia_teams.py --teste     mostra o que baixaria, sem salvar nem reagir
    python vigia_teams.py --login     refaz o login da conta Microsoft
    python vigia_teams.py --listar    lista suas equipes e canais (pega os IDs)
"""

import argparse
import base64
import datetime as dt
import json
import os
import sys
import time

try:
    import msal
    import requests
except ImportError:
    print("Faltam bibliotecas. Rode INSTALAR.bat ou:")
    print("    python -m pip install --user msal requests")
    sys.exit(1)

import graph_anexo
import marcar_no_grupo
import pastas


AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config_teams.json")
CACHE_TOKEN = os.path.join(AQUI, "token_teams.bin")
REGISTRO = os.path.join(AQUI, "ja_baixados_teams.json")
LOG = os.path.join(AQUI, "vigia_teams.log")

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_BETA = "https://graph.microsoft.com/beta"
# Files.ReadWrite.All e o que permite subir o arquivo para o OneDrive; sem ele
# o aviso no chat so conseguiria mandar link, nao anexo.
ESCOPOS = ["ChannelMessage.Read.All", "ChannelMessage.Send", "ChatMessage.Send",
           "Files.Read.All", "Files.ReadWrite.All", "User.Read"]


# ----------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------

def registrar(msg):
    carimbo = dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    linha = "[{}] {}".format(carimbo, msg)
    try:
        print(linha, flush=True)
    except UnicodeEncodeError:
        print(linha.encode("ascii", "replace").decode(), flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def mostrar_so_na_tela(texto):
    """Linha decorativa: aparece na janela, mas nao enche o arquivo de log."""
    try:
        print(texto, flush=True)
    except UnicodeEncodeError:
        print(texto.encode("ascii", "replace").decode(), flush=True)


def anunciar_salvo(cliente, destino, tamanho, quem=None):
    """Deixa bem visivel na tela de qual cliente era o arquivo que acabou de ser salvo."""
    barra = "=" * 64
    mostrar_so_na_tela(barra)
    registrar("ARQUIVO SALVO  >>  CLIENTE: {}".format(cliente))
    registrar("    Arquivo: {} ({:.1f} MB)".format(os.path.basename(destino), tamanho / 1048576))
    if quem:
        registrar("    Enviado por: {}".format(quem))
    registrar("    Pasta: {}".format(os.path.dirname(destino)))
    mostrar_so_na_tela(barra)


ULTIMO_ESTADO = {"valor": None}


def avisar_estado(texto):
    """Registra so quando o estado muda (nao enche o log a cada checagem)."""
    if ULTIMO_ESTADO["valor"] != texto:
        ULTIMO_ESTADO["valor"] = texto
        registrar(texto)


def ler_config():
    if not os.path.exists(CONFIG):
        registrar("ERRO: config_teams.json nao encontrado ao lado do script.")
        sys.exit(1)
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for campo in ("client_id", "tenant_id"):
        valor = cfg.get(campo) or ""
        if not valor or valor.startswith("COLE"):
            registrar("ERRO: preencha '{}' no config_teams.json.".format(campo))
            sys.exit(1)
    return cfg


def nome_do_cliente(cfg):
    """Nome do cliente desse canal: a pasta dele no servidor (ou o nome do canal)."""
    base = (cfg.get("pasta_base") or "").rstrip("\\/")
    return (cfg.get("nome_do_cliente") or os.path.basename(base)
            or cfg.get("nome_do_canal") or "cliente")


# ----------------------------------------------------------------------
# login na Microsoft
# ----------------------------------------------------------------------

def obter_token(cfg, forcar_login=False):
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_TOKEN):
        try:
            with open(CACHE_TOKEN, "r", encoding="utf-8") as f:
                cache.deserialize(f.read())
        except OSError:
            pass

    app = msal.PublicClientApplication(
        cfg["client_id"],
        authority="https://login.microsoftonline.com/{}".format(cfg["tenant_id"]),
        token_cache=cache,
    )

    resultado = None
    if not forcar_login:
        contas = app.get_accounts()
        if contas:
            resultado = app.acquire_token_silent(ESCOPOS, account=contas[0])

    if not resultado:
        # Dois jeitos de entrar:
        #   navegador -> abre a pagina de login no navegador do PC (padrao)
        #   codigo    -> mostra um codigo para digitar em outro aparelho
        # Muitas empresas bloqueiam o modo "codigo" por politica de seguranca
        # (erro 530035), por isso o padrao e o navegador.
        modo = (cfg.get("modo_login") or "navegador").strip().lower()
        if modo.startswith("nav"):
            print("")
            print("=" * 64)
            print("  LOGIN DA MICROSOFT - vou abrir o navegador")
            print("  Entre com a conta da empresa e aceite as permissoes.")
            print("=" * 64)
            print("", flush=True)
            try:
                resultado = app.acquire_token_interactive(ESCOPOS, prompt="select_account")
            except Exception as e:
                registrar("AVISO: login pelo navegador falhou ({}). Tentando pelo codigo.".format(e))
                resultado = None
        if not resultado:
            fluxo = app.initiate_device_flow(scopes=ESCOPOS)
            if "user_code" not in fluxo:
                registrar("ERRO ao iniciar o login: {}".format(fluxo.get("error_description")))
                return None
            print("")
            print("=" * 64)
            print("  LOGIN DA MICROSOFT - so precisa fazer isso uma vez")
            print("=" * 64)
            print(fluxo["message"])
            print("=" * 64)
            print("", flush=True)
            resultado = app.acquire_token_by_device_flow(fluxo)

    if cache.has_state_changed:
        try:
            with open(CACHE_TOKEN, "w", encoding="utf-8") as f:
                f.write(cache.serialize())
        except OSError as e:
            registrar("AVISO: nao consegui salvar o token: {}".format(e))

    if not resultado or "access_token" not in resultado:
        registrar("ERRO de login: {}".format((resultado or {}).get("error_description", "sem token")))
        return None
    return resultado["access_token"]


# ----------------------------------------------------------------------
# chamadas ao Graph
# ----------------------------------------------------------------------

class ErroGraph(Exception):
    def __init__(self, status, texto):
        super().__init__("HTTP {}: {}".format(status, (texto or "")[:300]))
        self.status = status


def graph(token, metodo, url, **kwargs):
    if url.startswith("/"):
        url = GRAPH + url
    cabecalho = {"Authorization": "Bearer " + token}
    cabecalho.update(kwargs.pop("headers", {}))
    for _ in range(4):
        r = requests.request(metodo, url, headers=cabecalho, timeout=120, **kwargs)
        if r.status_code == 429 or r.status_code >= 500:
            espera = int(r.headers.get("Retry-After", 5))
            registrar("API ocupada ({}), esperando {}s.".format(r.status_code, espera))
            time.sleep(espera)
            continue
        if r.status_code >= 400:
            raise ErroGraph(r.status_code, r.text)
        return r
    raise ErroGraph(r.status_code, r.text)


def graph_json(token, url, **kwargs):
    return graph(token, "GET", url, **kwargs).json()


def listar_equipes(token):
    equipes = graph_json(token, "/me/joinedTeams").get("value", [])
    for eq in equipes:
        print("\nEQUIPE: {}\n  team_id: {}".format(eq.get("displayName"), eq.get("id")))
        try:
            canais = graph_json(token, "/teams/{}/channels".format(eq["id"])).get("value", [])
        except ErroGraph as e:
            print("  (nao consegui listar os canais: {})".format(e))
            continue
        for c in canais:
            print("  CANAL: {}\n    channel_id: {}".format(c.get("displayName"), c.get("id")))


def mensagens_do_canal(token, cfg, horas):
    """Mensagens principais e respostas recentes do canal."""
    limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=horas)
    base = "/teams/{}/channels/{}/messages".format(cfg["team_id"], cfg["channel_id"])
    dados = graph_json(token, base + "?$top={}".format(int(cfg.get("mensagens_por_checagem", 20))))
    saida = []
    for msg in dados.get("value", []):
        saida.append((msg, None))
        if quando_da_mensagem(msg, "lastModifiedDateTime") < limite:
            continue
        try:
            respostas = graph_json(token, "{}/{}/replies?$top=30".format(base, msg["id"]))
        except ErroGraph as e:
            registrar("AVISO: nao consegui ler as respostas de {}: {}".format(msg["id"], e))
            continue
        for resp in respostas.get("value", []):
            saida.append((resp, msg["id"]))
    return saida


def baixar_anexo(token, content_url):
    """Baixa o arquivo pelo endereco que veio no anexo da mensagem."""
    chave = base64.urlsafe_b64encode(content_url.encode("utf-8")).decode("ascii").rstrip("=")
    r = graph(token, "GET", "/shares/u!{}/driveItem/content".format(chave))
    return r.content


def reagir(token, cfg, msg_id, pai_id):
    """Marca a mensagem com o emoji configurado (padrao ✅)."""
    emoji = cfg.get("emoji_reacao") or "✅"
    if pai_id:
        caminho = "/teams/{}/channels/{}/messages/{}/replies/{}/setReaction".format(
            cfg["team_id"], cfg["channel_id"], pai_id, msg_id)
    else:
        caminho = "/teams/{}/channels/{}/messages/{}/setReaction".format(
            cfg["team_id"], cfg["channel_id"], msg_id)
    corpo = {"reactionType": emoji}
    ultimo = None
    for base in (GRAPH, GRAPH_BETA):
        try:
            graph(token, "POST", base + caminho, json=corpo)
            return True
        except ErroGraph as e:
            ultimo = e
    registrar("AVISO: nao consegui reagir na mensagem ({}).".format(ultimo))
    return False


def _html(texto):
    return (texto.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def avisar_no_chat(token, cfg, arquivos):
    """Depois de salvar, manda os arquivos como anexo no chat configurado.

    arquivos = lista de (nome, caminho_no_disco, link). Se falhar, so registra
    no log: o arquivo ja esta salvo na pasta e nao e baixado de novo.
    """
    chat_id = (cfg.get("chat_aviso_id") or "").strip()
    if not chat_id or not arquivos or not cfg.get("avisar_no_chat", True):
        return False
    titulo = cfg.get("mensagem_aviso") or "Arquivo recebido e em produção:"

    emails = cfg.get("emails_chat_aviso") or []
    erros = (ErroGraph, requests.RequestException, OSError, KeyError, ValueError)

    subidos = []
    links = []  # (nome, link que abre sem login)
    for nome, caminho, link_canal in arquivos:
        item = None
        try:
            item = graph_anexo.subir(graph, token, caminho, nome)
            subidos.append((nome, item))
        except erros as e:
            registrar("AVISO: nao consegui subir '{}' para anexar ({}).".format(nome, e))

        if item:
            # libera o anexo para o cliente (sem isso: "Voce precisa de acesso")
            try:
                graph_anexo.liberar_para(graph, token, item, emails)
            except erros as e:
                registrar("AVISO: nao consegui liberar o anexo '{}' para {} ({}).".format(nome, emails, e))
        else:
            # sem anexo: usa o proprio arquivo do canal no SharePoint
            try:
                item = graph_anexo.item_pelo_link(graph, token, link_canal)
            except erros as e:
                registrar("AVISO: nao achei '{}' no SharePoint ({}).".format(nome, e))

        link = ""
        if item and cfg.get("link_publico_no_chat", True):
            try:
                link = graph_anexo.link_publico(graph, token, item)
            except erros as e:
                registrar("AVISO: nao consegui criar link publico de '{}' ({}).".format(nome, e))
        links.append((nome, link or link_canal.replace(" ", "%20")))

    links_html = "".join('<p><a href="{}">{}</a></p>'.format(_html(l), _html(n)) for n, l in links)
    if subidos:
        corpo = graph_anexo.corpo_com_anexos(subidos, _html(titulo), links_html)
    else:
        registrar("AVISO: nenhum anexo subiu; mando o aviso so com o link.")
        corpo = {"body": {"contentType": "html", "content": "<p>{}</p>{}".format(_html(titulo), links_html)}}

    try:
        graph(token, "POST", "/chats/{}/messages".format(chat_id), json=corpo)
    except (ErroGraph, requests.RequestException) as e:
        registrar("AVISO: nao consegui mandar o aviso no chat ({}).".format(e))
        return False
    registrar("    Aviso enviado no chat ({} anexo(s)): {}".format(
        len(subidos), cfg.get("nome_do_chat_aviso") or chat_id))
    return True


# ----------------------------------------------------------------------
# registro do que ja foi baixado
# ----------------------------------------------------------------------

def ler_registro(cfg):
    if os.path.exists(REGISTRO):
        try:
            with open(REGISTRO, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    horas = float(cfg.get("horas_retroativas_primeira_vez", 12))
    registrar("Primeira execucao: vou pegar o que chegou nas ultimas {:g} horas.".format(horas))
    return {"desde": time.time() - horas * 3600, "baixados": []}


def gravar_registro(reg):
    reg["baixados"] = reg["baixados"][-20000:]
    tmp = REGISTRO + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
        os.replace(tmp, REGISTRO)
    except OSError as e:
        registrar("AVISO: nao consegui gravar o registro: {}".format(e))


# ----------------------------------------------------------------------
# passada
# ----------------------------------------------------------------------

def quando_da_mensagem(msg, campo="createdDateTime"):
    texto = msg.get(campo) or msg.get("createdDateTime") or ""
    try:
        return dt.datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return dt.datetime.now(dt.timezone.utc)


def anexos_de_arquivo(cfg, msg):
    aceitas = [e.lower() for e in (cfg.get("extensoes_aceitas") or [])]
    saida = []
    for anexo in msg.get("attachments") or []:
        if (anexo.get("contentType") or "") != "reference":
            continue
        nome = anexo.get("name") or ""
        if not anexo.get("contentUrl"):
            continue
        if aceitas and os.path.splitext(nome)[1].lower() not in aceitas:
            continue
        saida.append(anexo)
    return saida


def de_outra_pessoa(cfg, msg, meu_id):
    if not cfg.get("ignorar_meus_envios", True):
        return True
    remetente = ((msg.get("from") or {}).get("user") or {})
    return (remetente.get("id") or "") != meu_id


def uma_passada(cfg, modo_teste=False):
    token = obter_token(cfg)
    if not token:
        return 0

    try:
        eu = graph_json(token, "/me")
        meu_id = eu.get("id") or ""
        mensagens = mensagens_do_canal(token, cfg, float(cfg.get("horas_para_ver_respostas", 72)))
    except (ErroGraph, requests.RequestException) as e:
        avisar_estado("Nao consegui falar com a Microsoft agora ({}). Tento de novo.".format(e))
        return 0
    avisar_estado("Conectado no canal '{}'. Aguardando arquivos...".format(
        cfg.get("nome_do_canal") or cfg["channel_id"]))

    reg = ler_registro(cfg)
    ja = set(reg["baixados"])
    desde = dt.datetime.fromtimestamp(reg.get("desde", 0), dt.timezone.utc)

    salvos = 0
    nomes_da_passada = []
    for msg, pai_id in sorted(mensagens, key=lambda m: quando_da_mensagem(m[0])):
        quando_utc = quando_da_mensagem(msg)
        if quando_utc < desde or not de_outra_pessoa(cfg, msg, meu_id):
            continue
        anexos = anexos_de_arquivo(cfg, msg)
        if not anexos:
            continue
        quando = quando_utc.astimezone().replace(tzinfo=None)
        quem = ((msg.get("from") or {}).get("user") or {}).get("displayName") or "alguem"

        baixou_algum = False
        salvos_nesta_msg = []
        for anexo in anexos:
            marca = "{}|{}".format(msg["id"], anexo.get("id") or anexo.get("name"))
            if marca in ja:
                continue
            nome = anexo.get("name") or "arquivo"

            if modo_teste:
                registrar("[TESTE] {} mandou '{}' em {} - iria para a pasta do dia{}".format(
                    quem, nome, quando.strftime("%d/%m %H:%M"),
                    " e seria avisado no chat" if cfg.get("chat_aviso_id") and cfg.get("avisar_no_chat", True) else ""))
                continue

            try:
                dados = baixar_anexo(token, anexo["contentUrl"])
            except (ErroGraph, requests.RequestException) as e:
                registrar("ERRO ao baixar '{}': {}".format(nome, e))
                continue

            try:
                pasta = pastas.pasta_do_dia(cfg, quando, avisar=registrar)
                destino = pastas.gravar_arquivo(pasta, nome, dados)
            except OSError as e:
                registrar("ERRO ao salvar '{}': {}".format(nome, e))
                continue

            anunciar_salvo(nome_do_cliente(cfg), destino, len(dados), quem)
            ja.add(marca)
            reg["baixados"].append(marca)
            gravar_registro(reg)
            salvos += 1
            baixou_algum = True
            salvos_nesta_msg.append((nome, destino, anexo["contentUrl"]))
            nomes_da_passada.append(nome)

        if baixou_algum and not modo_teste:
            reagir(token, cfg, msg["id"], pai_id)
            avisar_no_chat(token, cfg, salvos_nesta_msg)

    if not modo_teste:
        # roda mesmo sem arquivo novo: as OS que ficaram pendentes esperando o
        # anuncio no grupo precisam ser tentadas de novo a cada passada
        try:
            marcar_no_grupo.processar(cfg, nomes_da_passada, registrar)
        except Exception as e:
            registrar("AVISO: falhou ao marcar no grupo do WhatsApp ({}).".format(e))
    return salvos


def vigiar(cfg):
    intervalo = int(cfg.get("segundos_entre_checagens", 60))
    registrar("Vigiando o canal do Teams (a cada {}s). Feche a janela para parar.".format(intervalo))
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
        except (SystemExit, ValueError, OSError) as e:
            registrar("AVISO: config_teams.json com problema, mantendo o anterior ({}).".format(e))


def main():
    p = argparse.ArgumentParser(description="Baixa os arquivos do canal do Teams para a pasta do dia.")
    p.add_argument("--vigiar", action="store_true", help="fica rodando e checando sozinho")
    p.add_argument("--teste", action="store_true", help="mostra o que baixaria, sem salvar")
    p.add_argument("--login", action="store_true", help="refaz o login da conta Microsoft")
    p.add_argument("--listar", action="store_true", help="lista suas equipes e canais com os IDs")
    args = p.parse_args()

    cfg = ler_config()

    if args.login:
        token = obter_token(cfg, forcar_login=True)
        if token:
            eu = graph_json(token, "/me")
            registrar("Login feito como {} ({}).".format(eu.get("displayName"), eu.get("userPrincipalName")))
        return

    if args.listar:
        token = obter_token(cfg)
        if token:
            listar_equipes(token)
        return

    if args.vigiar:
        vigiar(cfg)
    else:
        n = uma_passada(cfg, modo_teste=args.teste)
        if not args.teste:
            registrar("{} arquivo(s) salvo(s).".format(n))


if __name__ == "__main__":
    main()

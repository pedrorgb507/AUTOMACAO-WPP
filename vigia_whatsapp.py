# -*- coding: utf-8 -*-
"""
VIGIA WHATSAPP - baixa os documentos que os clientes mandam no WhatsApp
e salva na pasta do dia de cada cliente.

Conversa com o OpenWA (rodando no mesmo PC) pela API local. Nao precisa de
biblioteca extra: so Python.

Uso:
    python vigia_whatsapp.py            uma passada
    python vigia_whatsapp.py --vigiar   fica rodando e checa a cada N segundos
    python vigia_whatsapp.py --teste    mostra o que baixaria, sem salvar nada
"""

import argparse
import base64
import datetime as dt
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config.json")
LOG = os.path.join(AQUI, "vigia.log")
REGISTRO = os.path.join(AQUI, "ja_baixados.json")


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


def ler_config():
    if not os.path.exists(CONFIG):
        registrar("ERRO: config.json nao encontrado ao lado do script.")
        sys.exit(1)
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("clientes"):
        registrar("ERRO: nenhum cliente cadastrado no config.json.")
        sys.exit(1)
    return cfg


def ler_api_key(cfg):
    chave = (cfg.get("api_key") or "").strip()
    if chave:
        return chave
    caminho = cfg.get("arquivo_api_key") or ""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


# ----------------------------------------------------------------------
# API do OpenWA
# ----------------------------------------------------------------------

class ErroApi(Exception):
    def __init__(self, status, texto):
        super().__init__("HTTP {}: {}".format(status, texto[:200]))
        self.status = status


# A API do OpenWA corta em 10 chamadas por segundo (HTTP 429). Cada cliente da
# lista soma uma chamada na rajada de cada passada, entao um respiro minimo
# entre chamadas mantem a folga por mais clientes que entrem no config.
_INTERVALO_MINIMO = 0.15
_ULTIMA_CHAMADA = {"quando": 0.0}


def respirar():
    espera = _INTERVALO_MINIMO - (time.time() - _ULTIMA_CHAMADA["quando"])
    if espera > 0:
        time.sleep(espera)
    _ULTIMA_CHAMADA["quando"] = time.time()


def chamar(cfg, chave, caminho, params=None, binario=False, timeout=60, metodo="GET", corpo=None):
    respirar()
    url = cfg.get("openwa_url", "http://localhost:2785").rstrip("/") + caminho
    if params:
        url += "?" + urllib.parse.urlencode(params)
    cabecalhos = {"X-API-Key": chave, "Accept": "*/*"}
    dados_envio = None
    if corpo is not None:
        dados_envio = json.dumps(corpo).encode("utf-8")
        cabecalhos["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=dados_envio, headers=cabecalhos, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dados = resp.read()
    except urllib.error.HTTPError as e:
        corpo_erro = e.read().decode("utf-8", "replace") if e.fp else ""
        raise ErroApi(e.code, corpo_erro)
    if binario:
        return dados
    # alguns POSTs respondem 200 com corpo vazio; json.loads morreria neles
    if not dados.strip():
        return {}
    return json.loads(dados.decode("utf-8"))


def listar_sessoes(cfg, chave):
    """Sessoes do OpenWA que batem com o 'sessao' do config, em qualquer estado."""
    sessoes = chamar(cfg, chave, "/api/sessions")
    if isinstance(sessoes, dict):
        sessoes = sessoes.get("sessions") or sessoes.get("data") or []
    desejada = (cfg.get("sessao") or "").strip().lower()
    if not desejada:
        return list(sessoes)
    return [s for s in sessoes
            if desejada in (str(s.get("name", "")).lower(), str(s.get("id", "")).lower())]


def achar_sessao(cfg, chave):
    for s in listar_sessoes(cfg, chave):
        if s.get("status") == "ready":
            return s
    return None


# Estados em que a sessao ja esta de pe ou subindo sozinha: mandar 'start' de
# novo so atrapalharia.
ESTADOS_DE_PE = ("ready", "initializing", "connecting", "authenticating", "qr", "qr_ready")

# Estados em que o WhatsApp desvinculou o aparelho: a sessao so volta com
# alguem lendo o QR no painel. Mandar 'start' aqui nao adianta - antes desta
# lista existir, o vigia ficava pedindo start a cada minuto sem nunca resolver.
ESTADOS_DE_QR = ("qr", "qr_ready")

_ULTIMO_RELIGAR = {"quando": 0.0}


def religar_sessao(cfg, chave, minimo_entre_tentativas=60):
    """Religa a sessao que caiu com o servidor OpenWA ainda de pe.

    O AUTO_START_SESSIONS do OpenWA so vale no instante em que o servidor sobe;
    se a sessao cai depois disso, ela fica parada ate alguem religar na mao.
    Espaça as tentativas para nao martelar a API a cada checagem.
    Devolve True quando chegou a pedir o start.
    """
    agora = time.time()
    if agora - _ULTIMO_RELIGAR["quando"] < minimo_entre_tentativas:
        return False
    for s in listar_sessoes(cfg, chave):
        estado = str(s.get("status") or "").lower()
        if estado in ESTADOS_DE_QR:
            avisar_estado("WHATSAPP DESVINCULADO: a sessao '{}' esta esperando leitura do QR. "
                          "Abra o painel do OpenWA e escaneie com o celular; ate la nada e baixado.".format(
                              s.get("name")))
            return False
        if estado in ESTADOS_DE_PE:
            continue
        _ULTIMO_RELIGAR["quando"] = agora
        registrar("Sessao '{}' caiu (estado '{}'). Religando...".format(s.get("name"), s.get("status")))
        try:
            chamar(cfg, chave, "/api/sessions/{}/start".format(
                urllib.parse.quote(str(s.get("id") or ""), safe="")), metodo="POST")
        except (urllib.error.URLError, OSError, ErroApi) as e:
            registrar("Nao consegui religar a sessao '{}': {}".format(s.get("name"), e))
            return False
        return True
    return False


def variantes_numero(numero):
    """IDs possiveis do WhatsApp para um numero brasileiro.

    O WhatsApp as vezes guarda celular sem o nono digito (556293079801) e as
    vezes com ele (5562993079801). Testamos os dois.
    """
    d = re.sub(r"\D", "", numero or "")
    if d.startswith("55") and len(d) >= 12:
        d = d[2:]
    if len(d) < 10:
        return ["55" + d] if d else []
    ddd, resto = d[:2], d[2:]
    saida = ["55" + ddd + resto]
    if len(resto) == 9 and resto.startswith("9"):
        saida.append("55" + ddd + resto[1:])
    elif len(resto) == 8:
        saida.append("55" + ddd + "9" + resto)
    return saida


# Cache de numero -> id de chat do WhatsApp, para nao perguntar a mesma coisa
# a cada checagem. Vive so enquanto o vigia esta rodando.
_CACHE_CHAT_ID = {}


def chat_ids_do_numero(cfg, chave, sessao_id, num):
    """Ids de chat que o WhatsApp aceita para um numero.

    Contas novas usam endereco LID (ex.: 120715055526130@lid) no lugar do
    antigo 556293079801@c.us. O endpoint /contacts/check traduz o numero para
    o id certo; se ele falhar, caimos no formato antigo.
    """
    if num in _CACHE_CHAT_ID:
        return _CACHE_CHAT_ID[num]
    ids = []
    try:
        resp = chamar(cfg, chave, "/api/sessions/{}/contacts/check/{}".format(
            urllib.parse.quote(sessao_id, safe=""), urllib.parse.quote(num, safe="")))
        if isinstance(resp, dict) and resp.get("exists") and resp.get("whatsappId"):
            ids.append(resp["whatsappId"])
    except (ErroApi, OSError, ValueError):
        pass
    traduziu = bool(ids)
    ids.append(num + "@c.us")
    if traduziu:
        # so guarda no cache quando a traducao deu certo; assim um erro
        # passageiro de rede nao congela o formato antigo pro resto do dia
        _CACHE_CHAT_ID[num] = ids
    return ids


def mensagens_do_chat(cfg, chave, sessao_id, chat_ids):
    """Ultimas mensagens de um ou mais chats, sem repetir a mesma mensagem.

    Numero e grupo chegam aqui do mesmo jeito: a unica diferenca entre os dois
    e como se descobre o chat_id.
    """
    vistas = {}
    for chat_id in chat_ids:
        try:
            resp = chamar(cfg, chave, "/api/sessions/{}/messages".format(urllib.parse.quote(sessao_id, safe="")),
                          {"chatId": chat_id, "limit": 50, "inlineMedia": "false"})
        except ErroApi as e:
            if e.status in (400, 404):
                continue
            raise
        for m in resp.get("messages", []) if isinstance(resp, dict) else []:
            chave_msg = m.get("waMessageId") or m.get("id")
            if chave_msg:
                vistas[chave_msg] = m
    return list(vistas.values())


# Cache de nome de grupo -> id (...@g.us). Vive so enquanto o vigia esta rodando.
_CACHE_GRUPO_ID = {}
_GRUPO_JA_AVISADO = set()


def chat_id_do_grupo(cfg, chave, sessao_id, nome):
    """Id do chat de um grupo, procurado pelo nome que aparece no WhatsApp.

    A API nao busca grupo por nome: e preciso listar todos e comparar. A
    comparacao passa por normalizar() porque o nome digitado no config
    dificilmente bate letra a letra com o assunto do grupo (maiuscula, acento,
    espaco sobrando).
    """
    if nome in _CACHE_GRUPO_ID:
        return _CACHE_GRUPO_ID[nome]
    try:
        grupos = chamar(cfg, chave, "/api/sessions/{}/groups".format(
            urllib.parse.quote(sessao_id, safe="")))
    except (ErroApi, OSError, ValueError) as e:
        registrar("ERRO ao listar os grupos do WhatsApp: {}".format(e))
        return None
    if isinstance(grupos, dict):
        grupos = grupos.get("groups") or grupos.get("data") or []
    alvo = normalizar(nome)
    for g in grupos:
        if normalizar(str(g.get("name") or "")) == alvo:
            _CACHE_GRUPO_ID[nome] = g.get("id")
            return g.get("id")
    # sem a lista de grupos visiveis, quem configurou nao tem como saber se
    # errou o nome ou se o numero do robo nao esta dentro do grupo
    if nome not in _GRUPO_JA_AVISADO:
        _GRUPO_JA_AVISADO.add(nome)
        registrar("AVISO: grupo '{}' nao encontrado. Grupos que enxergo: {}".format(
            nome, ", ".join(sorted(str(g.get("name") or "?") for g in grupos)) or "(nenhum)"))
    return None


def mensagens_do_cliente(cfg, chave, sessao_id, cliente):
    """Ultimas mensagens recebidas do cliente (do banco do OpenWA)."""
    grupo = (cliente.get("grupo") or "").strip()
    if grupo:
        chat_id = chat_id_do_grupo(cfg, chave, sessao_id, grupo)
        return [] if not chat_id else mensagens_do_chat(cfg, chave, sessao_id, [chat_id])
    # As duas variantes do numero (com e sem o nono digito) quase sempre levam
    # ao MESMO chat, e o @c.us so serve quando a traducao falhou. Consultar tudo
    # gastaria 4 chamadas por cliente e estoura o limite de 10 por segundo da
    # API. Por isso a lista e reduzida a um alvo antes de sair consultando.
    alvos = []
    for num in variantes_numero(cliente.get("whatsapp")):
        ids = chat_ids_do_numero(cfg, chave, sessao_id, num)
        for chat_id in ids:
            if chat_id not in alvos:
                alvos.append(chat_id)
        if any(not c.endswith("@c.us") for c in ids):
            break  # traduziu: a outra variante levaria ao mesmo chat
    traduzidos = [c for c in alvos if not c.endswith("@c.us")]
    if traduzidos:
        alvos = traduzidos

    return mensagens_do_chat(cfg, chave, sessao_id, alvos)


# Emoji que marca no WhatsApp a mensagem cujo arquivo ja foi baixado: o cliente
# ve o visto na propria conversa e sabe que chegou. Trocavel pelo config.
EMOJI_OK = "✅"


def reagir(cfg, chave, sessao_id, chat_id, wid):
    """Marca a mensagem com o visto de recebido.

    Chamada so depois do arquivo estar salvo e registrado: a reacao e aviso ao
    cliente, nao parte do download.
    """
    emoji = cfg.get("reacao_ao_baixar", EMOJI_OK)
    if not emoji or not chat_id or not wid:
        return
    chamar(cfg, chave, "/api/sessions/{}/messages/react".format(
        urllib.parse.quote(sessao_id, safe="")),
        metodo="POST",
        corpo={"chatId": chat_id, "messageId": wid, "emoji": emoji})


# ----------------------------------------------------------------------
# pasta do dia (mesma logica do VIGIA SOLIDA)
# ----------------------------------------------------------------------

MESES = ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO",
         "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]

MESES_ACENTUADOS = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
                    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]


def montar_subpasta(cfg, quando):
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


def pasta_do_dia(cfg, cliente, quando):
    base = cfg["pasta_trabalho"]
    if not os.path.isdir(base):
        raise OSError("pasta de trabalho inacessivel: {}".format(base))
    nome_cliente = achar_pasta_existente(base, cliente["pasta"])
    caminho = os.path.join(base, nome_cliente)
    if not os.path.isdir(caminho):
        registrar("AVISO: pasta do cliente nao existia, criando: {}".format(caminho))
    for parte in montar_subpasta(cfg, quando).replace("/", "\\").split("\\"):
        if parte:
            caminho = os.path.join(caminho, achar_pasta_existente(caminho, parte))
    os.makedirs(caminho, exist_ok=True)
    return caminho


PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


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


EXTENSOES_POR_MIME = {
    "application/pdf": ".pdf", "application/zip": ".zip", "application/x-rar-compressed": ".rar",
    "image/jpeg": ".jpg", "image/png": ".png", "image/tiff": ".tif", "application/postscript": ".eps",
    "video/mp4": ".mp4", "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
}


def nome_do_arquivo(msg, quando):
    media = (msg.get("metadata") or {}).get("media") or {}
    nome = media.get("filename") or ""
    if not nome:
        # sem nome original: usa a legenda ou a hora de envio
        legenda = (msg.get("body") or "").strip().splitlines()
        nome = legenda[0][:80] if legenda and msg.get("type") == "document" else ""
        nome = nome or "whatsapp_" + quando.strftime("%Y%m%d_%H%M%S")
        ext = EXTENSOES_POR_MIME.get((media.get("mimetype") or "").split(";")[0].strip().lower(), "")
        if ext and not nome.lower().endswith(ext):
            nome += ext
    return nome_seguro(nome)


# ----------------------------------------------------------------------
# registro do que ja foi baixado
# ----------------------------------------------------------------------

def ler_registro():
    if not os.path.exists(REGISTRO):
        return None
    try:
        with open(REGISTRO, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


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

# Historico ao vivo ja buscado nesta passada, por chat. A busca e cara (baixa a
# midia de varias mensagens de uma vez), entao uma por chat por passada basta
# para atender todas as mensagens que falharam naquele chat.
_HISTORICO_DA_PASSADA = {}


def midia_pelo_historico(cfg, chave, sessao_id, msg, limite=8, timeout=240):
    """Conteudo do anexo lido direto do WhatsApp, sem passar pelo banco do OpenWA.

    O OpenWA nao guarda a midia de mensagem que chegou enquanto ele estava fora
    do ar, e nao busca depois. Este endpoint le do proprio aparelho, que e o
    unico jeito de recuperar esses arquivos. Devolve os bytes ou None.
    """
    chat_id = msg.get("chatId") or ""
    if chat_id not in _HISTORICO_DA_PASSADA:
        try:
            resp = chamar(cfg, chave, "/api/sessions/{}/messages/{}/history".format(
                urllib.parse.quote(sessao_id, safe=""), urllib.parse.quote(chat_id, safe="")),
                {"limit": limite, "includeMedia": "true"}, timeout=timeout)
            itens = resp.get("messages", resp) if isinstance(resp, dict) else resp
            _HISTORICO_DA_PASSADA[chat_id] = itens or []
        except (ErroApi, urllib.error.URLError, OSError, ValueError) as e:
            registrar("AVISO: nao consegui ler o historico ao vivo de {} ({}).".format(chat_id, e))
            _HISTORICO_DA_PASSADA[chat_id] = []

    alvo = msg.get("waMessageId")
    for m in _HISTORICO_DA_PASSADA[chat_id]:
        if m.get("id") != alvo:
            continue
        bruto = (m.get("media") or {}).get("data") or (m.get("media") or {}).get("base64")
        if not bruto:
            return None
        try:
            return base64.b64decode(bruto)
        except (ValueError, TypeError):
            return None
    return None


def quando_da_mensagem(msg):
    ts = msg.get("timestamp")
    if isinstance(ts, (int, float)) and ts > 0:
        return dt.datetime.fromtimestamp(ts)
    criado = msg.get("createdAt") or ""
    try:
        return dt.datetime.fromisoformat(criado.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return dt.datetime.now()


def interessa(cfg, msg):
    if msg.get("direction") != "incoming":
        return False
    if msg.get("type") not in (cfg.get("tipos") or ["document"]):
        return False
    aceitas = [e.lower() for e in (cfg.get("extensoes_aceitas") or [])]
    if aceitas:
        media = (msg.get("metadata") or {}).get("media") or {}
        ext = os.path.splitext(media.get("filename") or "")[1].lower()
        if ext not in aceitas:
            return False
    return True


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
    """Registra so quando o estado muda (evita encher o log a cada 20s)."""
    if ULTIMO_ESTADO["valor"] != texto:
        ULTIMO_ESTADO["valor"] = texto
        registrar(texto)


def uma_passada(cfg, modo_teste=False):
    chave = ler_api_key(cfg)
    if not chave:
        registrar("ERRO: API Key nao encontrada ({}).".format(cfg.get("arquivo_api_key")))
        return 0

    try:
        sessao = achar_sessao(cfg, chave)
    except (urllib.error.URLError, OSError, ErroApi) as e:
        avisar_estado("OpenWA fora do ar ou recusou a chave ({}). Tento de novo a cada checagem.".format(e))
        return 0
    if not sessao:
        try:
            religou = religar_sessao(cfg, chave)
        except (urllib.error.URLError, OSError, ErroApi):
            religou = False
        if not religou:
            avisar_estado("Nenhuma sessao do WhatsApp conectada no OpenWA. Tento de novo a cada checagem.")
        return 0
    avisar_estado("Conectado na sessao '{}' ({}). Aguardando arquivos...".format(
        sessao.get("name"), sessao.get("phone") or "numero ?"))

    reg = ler_registro()
    if reg is None:
        horas = float(cfg.get("horas_retroativas_primeira_vez", 12))
        reg = {"desde": time.time() - horas * 3600, "baixados": []}
        gravar_registro(reg)
        registrar("Primeira execucao: vou baixar o que chegou nas ultimas {:g} horas.".format(horas))
    ja = set(reg["baixados"])
    desde = dt.datetime.fromtimestamp(reg.get("desde", 0))

    salvos = 0
    _HISTORICO_DA_PASSADA.clear()
    for cliente in cfg["clientes"]:
        try:
            msgs = mensagens_do_cliente(cfg, chave, sessao["id"], cliente)
        except (urllib.error.URLError, OSError, ErroApi) as e:
            registrar("ERRO ao consultar {}: {}".format(cliente.get("pasta"), e))
            continue

        for msg in sorted(msgs, key=lambda m: m.get("timestamp") or 0):
            wid = msg.get("waMessageId")
            if not wid or wid in ja or not interessa(cfg, msg):
                continue
            quando = quando_da_mensagem(msg)
            if quando < desde:
                continue
            nome = nome_do_arquivo(msg, quando)

            if modo_teste:
                registrar("[TESTE] {} -> {} ({})".format(cliente["pasta"], nome, quando.strftime("%d/%m %H:%M")))
                continue

            try:
                dados = chamar(cfg, chave, "/api/sessions/{}/messages/{}/{}/media".format(
                    urllib.parse.quote(sessao["id"], safe=""),
                    urllib.parse.quote(msg.get("chatId") or "", safe=""),
                    urllib.parse.quote(wid, safe="")), binario=True, timeout=300)
            except ErroApi as e:
                if e.status != 404:
                    registrar("ERRO ao baixar '{}': {}".format(nome, e))
                    continue
                # O OpenWA nao tem a midia. Antes de desistir, tenta ler direto
                # do aparelho: e assim que se recupera o que chegou enquanto ele
                # estava fora do ar.
                dados = midia_pelo_historico(cfg, chave, sessao["id"], msg)
                if not dados:
                    velha = (dt.datetime.now() - quando).total_seconds() > 600
                    if not velha:
                        registrar("AVISO: '{}' de {} ainda nao tem o arquivo no OpenWA; tento de novo.".format(
                            nome, cliente["pasta"]))
                        continue
                    # desistir marcando como baixado esconderia a perda; entao o
                    # aviso final tem que ser inconfundivel
                    registrar("ARQUIVO PERDIDO  >>  CLIENTE: {}".format(cliente["pasta"]))
                    registrar("    Arquivo: {}".format(nome))
                    registrar("    Chegou em {} e o OpenWA nunca guardou o conteudo.".format(
                        quando.strftime("%d/%m %H:%M")))
                    registrar("    BAIXE ESTE A MAO pelo WhatsApp; nao vou tentar de novo.")
                    ja.add(wid)
                    reg["baixados"].append(wid)
                    gravar_registro(reg)
                    continue
                registrar("    ('{}' recuperado pelo historico ao vivo.)".format(nome))
            except (urllib.error.URLError, OSError) as e:
                registrar("ERRO ao baixar '{}': {}".format(nome, e))
                continue

            try:
                pasta = pasta_do_dia(cfg, cliente, quando)
                destino = nome_livre(pasta, nome)
                with open(destino + ".parte", "wb") as f:
                    f.write(dados)
                os.replace(destino + ".parte", destino)
            except OSError as e:
                registrar("ERRO ao salvar '{}' de {}: {}".format(nome, cliente["pasta"], e))
                continue

            anunciar_salvo(cliente["pasta"], destino, len(dados))
            ja.add(wid)
            reg["baixados"].append(wid)
            gravar_registro(reg)
            salvos += 1

            try:
                reagir(cfg, chave, sessao["id"], msg.get("chatId") or "", wid)
            except (urllib.error.URLError, OSError, ErroApi) as e:
                # o arquivo ja esta salvo e marcado como baixado; perder o visto
                # nao pode fazer o arquivo ser baixado de novo na proxima passada
                registrar("AVISO: '{}' foi salvo, mas nao consegui marcar o OK no WhatsApp: {}".format(nome, e))
    return salvos


def nomes_dos_clientes(cfg):
    return ", ".join(c.get("pasta", "?") for c in cfg["clientes"])


def vigiar(cfg):
    intervalo = int(cfg.get("segundos_entre_checagens", 20))
    nomes = nomes_dos_clientes(cfg)
    registrar("Vigiando o WhatsApp de: {} (a cada {}s). Feche a janela para parar.".format(nomes, intervalo))
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
        # relê o config a cada volta: cliente novo entra sem reiniciar
        try:
            cfg = ler_config()
        except (SystemExit, ValueError, OSError) as e:
            registrar("AVISO: config.json com problema, mantendo o anterior ({}).".format(e))
            continue
        # registra a lista nova: sem isso o log segue mostrando a lista da
        # partida, e quem le acha que um cliente recem-adicionado ficou de fora
        if nomes_dos_clientes(cfg) != nomes:
            nomes = nomes_dos_clientes(cfg)
            intervalo = int(cfg.get("segundos_entre_checagens", 20))
            registrar("Lista de clientes mudou. Vigiando agora: {}.".format(nomes))


# Segura o socket da trava pelo tempo de vida do processo. Se a referencia
# fosse solta, o coletor fecharia o socket e liberaria a porta.
_TRAVA = {"socket": None}


def travar_instancia_unica(porta=48317):
    """Garante um vigia por vez. Devolve False se ja existe outro rodando.

    Dois vigias gravam no mesmo ja_baixados.json e um sobrescreve o registro do
    outro, o que faz o mesmo arquivo ser baixado duas vezes. A trava e uma porta
    local ocupada: ao contrario de um arquivo de trava, ela nao fica presa se o
    vigia for morto de forma abrupta - o Windows devolve a porta sozinho.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", porta))
        s.listen(1)
    except OSError:
        s.close()
        return False
    _TRAVA["socket"] = s
    return True


def main():
    p = argparse.ArgumentParser(description="Baixa documentos do WhatsApp para a pasta do dia do cliente.")
    p.add_argument("--vigiar", action="store_true", help="fica rodando e checando sozinho")
    p.add_argument("--teste", action="store_true", help="mostra o que baixaria, sem salvar")
    args = p.parse_args()

    cfg = ler_config()
    if args.vigiar:
        if not travar_instancia_unica():
            registrar("Ja existe um VIGIA rodando. Esta janela vai fechar para nao baixar arquivo repetido.")
            return
        vigiar(cfg)
    else:
        n = uma_passada(cfg, modo_teste=args.teste)
        if not args.teste:
            registrar("{} arquivo(s) salvo(s).".format(n))


if __name__ == "__main__":
    main()

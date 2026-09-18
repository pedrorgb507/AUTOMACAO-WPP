# -*- coding: utf-8 -*-
"""
VIGIA EMAIL - baixa os anexos que chegam na caixa do Gmail e salva na pasta
do dia do cliente.

Le a caixa por IMAP, sem biblioteca extra: so Python. O cliente e descoberto
pelo remetente, conforme a lista do config_email.json.

Uso:
    python vigia_email.py            uma passada
    python vigia_email.py --vigiar   fica rodando
    python vigia_email.py --teste    mostra o que baixaria, sem salvar nada
"""

import argparse
import datetime as dt
import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import sys
import time

import drive_api
import painel
import pastas


AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config_email.json")
LOG = os.path.join(AQUI, "vigia_email.log")
REGISTRO = os.path.join(AQUI, "ja_baixados_email.json")

MESES_IMAP = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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
        registrar("ERRO: config_email.json nao encontrado ao lado do script.")
        sys.exit(1)
    with open(CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for campo in ("usuario", "senha_app"):
        if not (cfg.get(campo) or "").strip():
            registrar("ERRO: preencha '{}' no config_email.json.".format(campo))
            sys.exit(1)
    if not cfg.get("clientes"):
        registrar("ERRO: nenhum cliente cadastrado no config_email.json.")
        sys.exit(1)
    return cfg


def ler_registro():
    try:
        with open(REGISTRO, "r", encoding="utf-8") as f:
            dados = json.load(f)
        dados.setdefault("baixados", [])
        return dados
    except (OSError, ValueError):
        return None


def gravar_registro(reg):
    # guarda so os ultimos: a caixa cresce para sempre e a lista nao precisa
    reg["baixados"] = reg["baixados"][-3000:]
    try:
        with open(REGISTRO, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def texto_do_cabecalho(valor):
    """Decodifica cabecalho que veio codificado (=?utf-8?B?...?=)."""
    if not valor:
        return ""
    partes = []
    for pedaco, codec in email.header.decode_header(valor):
        if isinstance(pedaco, bytes):
            partes.append(pedaco.decode(codec or "utf-8", "replace"))
        else:
            partes.append(pedaco)
    return "".join(partes)


def quando_da_mensagem(msg):
    try:
        quando = email.utils.parsedate_to_datetime(msg.get("Date"))
    except (TypeError, ValueError):
        return dt.datetime.now()
    if quando is None:
        return dt.datetime.now()
    if quando.tzinfo:
        quando = quando.astimezone().replace(tzinfo=None)
    return quando


def cliente_do_remetente(cfg, remetente):
    """Acha o cliente pelo endereco do remetente.

    O casamento e por pedaco de texto para aceitar tanto o endereco inteiro
    quanto so o dominio ("@fulano.com.br"), que e como a maioria dos clientes
    manda de varios enderecos diferentes.
    """
    alvo = (remetente or "").lower()
    for c in cfg["clientes"]:
        for marca in ([c.get("de")] if isinstance(c.get("de"), str) else (c.get("de") or [])):
            if marca and marca.lower().strip() in alvo:
                return c
    return None


def anexos_da_mensagem(cfg, msg):
    """Anexos que interessam: (nome, bytes). Ignora corpo e imagem embutida."""
    aceitas = [e.lower() for e in (cfg.get("extensoes_aceitas") or [])]
    limite = float(cfg.get("tamanho_maximo_mb", 100)) * 1048576
    saida = []
    for parte in msg.walk():
        if parte.get_content_maintype() == "multipart":
            continue
        nome = texto_do_cabecalho(parte.get_filename())
        if not nome:
            continue
        # imagem colada no corpo (assinatura, logo) vem como 'inline' e nao e anexo
        if (parte.get("Content-Disposition") or "").lower().startswith("inline"):
            continue
        if aceitas and os.path.splitext(nome)[1].lower() not in aceitas:
            continue
        try:
            dados = parte.get_payload(decode=True)
        except Exception:
            dados = None
        if not dados:
            continue
        if len(dados) > limite:
            registrar("AVISO: '{}' tem {:.1f} MB e passa do limite de {:g} MB; nao baixei.".format(
                nome, len(dados) / 1048576, float(cfg.get("tamanho_maximo_mb", 100))))
            continue
        saida.append((nome, dados))
    return saida



# Link que o Gmail poe no lugar do anexo quando o arquivo e grande demais.
RE_DRIVE = re.compile(r"drive\.google\.com/file/d/([\w-]+)")


def links_do_drive(msg):
    """Ids dos arquivos do Drive citados no corpo, sem repetir.

    Quando o anexo passa do limite do Gmail, o e-mail chega SEM anexo e com um
    link no corpo. Antes isso era lido como "e-mail sem nada para baixar" e o
    arquivo se perdia em silencio - que e pior do que um erro, porque ninguem
    fica sabendo.
    """
    ids = []
    for parte in msg.walk():
        if parte.get_content_type() not in ("text/plain", "text/html"):
            continue
        try:
            corpo = parte.get_payload(decode=True)
        except Exception:
            continue
        if not corpo:
            continue
        texto = corpo.decode(parte.get_content_charset() or "utf-8", "replace")
        for achado in RE_DRIVE.findall(texto):
            if achado not in ids:
                ids.append(achado)
    return ids


def anexos_do_drive(cfg, sessao, ids, assunto):
    """Baixa cada link e devolve (nome, bytes), no mesmo formato de um anexo.

    Assim o link entra no vigia pelo caminho de sempre, e o resto do codigo nao
    precisa saber que aquele arquivo veio de outro lugar.
    """
    limite = float(cfg.get("tamanho_maximo_drive_mb", 500)) * 1048576
    saida = []
    for id_arquivo in ids:
        try:
            nome, dados = sessao.baixar(id_arquivo)
        except Exception as e:
            registrar("ERRO ao baixar do Drive o link de '{}': {}".format(
                assunto[:40], str(e)[:110]))
            continue
        if len(dados) > limite:
            registrar("AVISO: '{}' tem {:.1f} MB e passa do limite do Drive"
                      " ({:g} MB); nao guardei.".format(
                          nome, len(dados) / 1048576, limite / 1048576))
            continue
        registrar("    veio por link do Drive: {} ({:.1f} MB)".format(nome, len(dados) / 1048576))
        saida.append((nome, dados))
    return saida


ULTIMO_ESTADO = {"valor": None}


def avisar_estado(texto):
    if ULTIMO_ESTADO["valor"] != texto:
        ULTIMO_ESTADO["valor"] = texto
        registrar(texto)


def conectar(cfg):
    caixa = imaplib.IMAP4_SSL(cfg.get("servidor_imap", "imap.gmail.com"),
                              int(cfg.get("porta", 993)))
    caixa.login(cfg["usuario"], cfg["senha_app"])
    caixa.select(cfg.get("pasta_imap", "INBOX"))
    return caixa


def ids_desde(caixa, desde):
    """UIDs das mensagens a partir da data. O IMAP filtra so por dia, entao a
    hora exata ainda e conferida depois, mensagem a mensagem."""
    marca = "{:02d}-{}-{}".format(desde.day, MESES_IMAP[desde.month - 1], desde.year)
    ok, resposta = caixa.uid("SEARCH", None, "SINCE", marca)
    if ok != "OK":
        return []
    return (resposta[0] or b"").split()


def uma_passada(cfg, modo_teste=False):
    # So nasce se algum e-mail trouxer link do Drive: abrir o Chrome custa caro
    # e a maioria dos e-mails tem anexo comum.
    sessao_drive = None
    reg = ler_registro()
    if reg is None:
        horas = float(cfg.get("horas_retroativas_primeira_vez", 12))
        reg = {"desde": time.time() - horas * 3600, "baixados": []}
        gravar_registro(reg)
        registrar("Primeira execucao: vou pegar o que chegou nas ultimas {:g} horas.".format(horas))
    ja = set(reg["baixados"])
    desde = dt.datetime.fromtimestamp(reg.get("desde", 0))

    try:
        caixa = conectar(cfg)
    except (imaplib.IMAP4.error, OSError) as e:
        avisar_estado("Nao consegui entrar na caixa {} ({}). Tento de novo.".format(cfg["usuario"], e))
        return 0
    avisar_estado("Conectado em {}. Aguardando e-mails...".format(cfg["usuario"]))

    salvos = 0
    try:
        for uid in ids_desde(caixa, desde):
            # primeiro so o cabecalho: descobrir de quem e custa alguns bytes,
            # enquanto baixar a mensagem inteira custa os anexos junto. Numa
            # caixa com milhares de e-mails de todo mundo, so uns poucos
            # remetentes interessam - o resto nem precisa ser transferido.
            ok, dados = caixa.uid("FETCH", uid,
                                  "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            if ok != "OK" or not dados or not dados[0]:
                continue
            cabecalho = email.message_from_bytes(dados[0][1])

            chave = (cabecalho.get("Message-ID") or "").strip() or "uid:" + uid.decode()
            if chave in ja:
                continue
            quando = quando_da_mensagem(cabecalho)
            if quando < desde:
                continue

            remetente = texto_do_cabecalho(cabecalho.get("From"))
            assunto = texto_do_cabecalho(cabecalho.get("Subject"))

            cliente_ja = cliente_do_remetente(cfg, remetente)
            if not cliente_ja and not (cfg.get("pasta_se_nao_reconhecer") or "").strip():
                # nao e de ninguem da lista: marca como visto e segue, sem baixar
                ja.add(chave)
                reg["baixados"].append(chave)
                continue

            # so agora vale a pena puxar a mensagem inteira
            ok, dados = caixa.uid("FETCH", uid, "(BODY.PEEK[])")
            if ok != "OK" or not dados or not dados[0]:
                continue
            msg = email.message_from_bytes(dados[0][1])
            anexos = anexos_da_mensagem(cfg, msg)
            # Sem anexo nao quer dizer sem arquivo: pode ter vindo por link do
            # Drive. So se procura link quando nao ha anexo, para nao baixar
            # duas vezes o que o cliente mandou dos dois jeitos.
            ids_drive = [] if anexos else links_do_drive(msg)
            if not anexos and not ids_drive:
                ja.add(chave)
                reg["baixados"].append(chave)
                continue

            cliente = cliente_ja
            if not cliente:
                padrao = (cfg.get("pasta_se_nao_reconhecer") or "").strip()
                if not padrao:
                    registrar("AVISO: nao sei de qual cliente e este e-mail; deixei sem baixar.")
                    registrar("    De: {} | Assunto: {}".format(remetente[:70], assunto[:50]))
                    registrar("    Anexos: {}".format(", ".join(n for n, _ in anexos)))
                    continue
                cliente = {"pasta": padrao}

            if ids_drive:
                if modo_teste:
                    registrar("[TESTE] {} -> {} link(s) do Drive em '{}'".format(
                        cliente["pasta"], len(ids_drive), assunto[:40]))
                else:
                    if sessao_drive is None:
                        sessao_drive = drive_api.SessaoDrive(
                            visivel=bool(cfg.get("mostrar_navegador", False)))
                    anexos = anexos + anexos_do_drive(cfg, sessao_drive, ids_drive, assunto)
                    if not anexos:
                        # nao registra: sem arquivo salvo, tenta de novo na
                        # proxima passada em vez de dar o e-mail por resolvido
                        continue

            salvou_algum = False
            # Os blocos so saem depois da tentativa de marcar como lido: um
            # e-mail pode trazer varios anexos, e a marcacao e do e-mail
            # inteiro. Imprimir antes obrigaria a adivinhar o resultado dela.
            blocos = []
            for nome, conteudo in anexos:
                if modo_teste:
                    registrar("[TESTE] {} -> {} ({:.1f} MB, de {})".format(
                        cliente["pasta"], nome, len(conteudo) / 1048576, remetente[:40]))
                    continue
                try:
                    pasta = pastas.pasta_do_dia_do_cliente(
                        cfg, cfg["pasta_trabalho"], cliente["pasta"], quando, avisar=registrar)
                    destino = pastas.gravar_arquivo(pasta, nome, conteudo)
                except OSError as e:
                    registrar("ERRO ao salvar '{}' de {}: {}".format(nome, cliente["pasta"], e))
                    continue
                blocos.append((cliente["pasta"], nome, len(conteudo), remetente, destino))
                salvos += 1
                salvou_algum = True

            if not modo_teste:
                ja.add(chave)
                reg["baixados"].append(chave)
                gravar_registro(reg)
                # so marca como lida se algum arquivo entrou mesmo. Se a gravacao
                # falhou, a mensagem tem que continuar em negrito chamando atencao.
                lido = None
                if salvou_algum and cfg.get("marcar_como_lido", False):
                    try:
                        caixa.uid("STORE", uid, "+FLAGS", "(" + chr(92) + "Seen)")
                        lido = True
                    except imaplib.IMAP4.error as e:
                        lido = False
                        registrar("AVISO: nao consegui marcar como lido ({}).".format(e))

                for pasta_cliente, nome_arq, tamanho, quem, caminho in blocos:
                    painel.bloco(LOG, pasta_cliente, [
                        ("ARQUIVO", "{} ({:.1f} MB)".format(nome_arq, tamanho / 1048576)),
                        ("DE", quem[:70]),
                        ("BAIXADO", "OK"),
                        ("MARCADO COMO LIDO", painel.ok_ou("FALHOU", lido)),
                        ("PASTA", os.path.dirname(caminho)),
                    ])
    finally:
        try:
            caixa.close()
            caixa.logout()
        except (imaplib.IMAP4.error, OSError):
            pass

    if not modo_teste:
        gravar_registro(reg)
    return salvos


def vigiar(cfg):
    intervalo = int(cfg.get("segundos_entre_checagens", 60))
    registrar("Vigiando a caixa {} (a cada {}s). Feche a janela para parar.".format(
        cfg["usuario"], intervalo))
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
    p = argparse.ArgumentParser(description="Baixa os anexos do e-mail para a pasta do dia do cliente.")
    p.add_argument("--vigiar", action="store_true", help="fica rodando")
    p.add_argument("--teste", action="store_true", help="mostra o que baixaria, sem salvar")
    args = p.parse_args()
    cfg = ler_config()
    if args.vigiar:
        vigiar(cfg)
    else:
        n = uma_passada(cfg, modo_teste=args.teste)
        if not args.teste:
            registrar("{} arquivo(s) salvo(s).".format(n))


if __name__ == "__main__":
    main()

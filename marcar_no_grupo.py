# -*- coding: utf-8 -*-
"""Marca no grupo do WhatsApp a OS cujo arquivo chegou pelo Teams.

A Solida anuncia cada servico por texto no grupo do WhatsApp ("49878 - Erre Efe
- tabloide") e manda o arquivo pelo canal do Teams. Quando o vigia do Teams
baixa o arquivo, a mensagem correspondente no grupo ganha o visto - e o pessoal
do grupo ve de relance o que ja entrou em producao.

O anuncio as vezes chega depois do arquivo. Por isso o arquivo nunca espera: ele
e baixado na hora e a OS fica pendente, tentada de novo a cada passada. Passando
do prazo do config, vira aviso de pendencia no log (uma vez por OS, para nao
encher o log a cada minuto).

Usa o vigia do WhatsApp para falar com o OpenWA em vez de duplicar a conversa
com a API.
"""

import json
import os
import time

import vigia_whatsapp as wa


AQUI = os.path.dirname(os.path.abspath(__file__))
PENDENCIAS = os.path.join(AQUI, "pendencias_os.json")

# cache do id do grupo e da sessao, para nao reperguntar a cada passada
_CACHE = {"grupo": None, "sessao": None}


def numero_da_os(texto):
    """Numero da OS no inicio do texto, ou None.

    Serve tanto para o nome do arquivo ("49862 - Miria Pires.pdf") quanto para a
    mensagem do grupo ("49862 - Miria Pires - folder corrigido"), que comecam
    igual. Como os dois passam por aqui, basta os dois concordarem.
    """
    digitos = ""
    for c in (texto or "").lstrip():
        if not c.isdigit():
            break
        digitos += c
    return digitos if len(digitos) >= 4 else None


def ler_pendencias():
    try:
        with open(PENDENCIAS, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def gravar_pendencias(dados):
    try:
        with open(PENDENCIAS, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _conectar(cfg_wa, registrar):
    """Devolve (chave, sessao_id, grupo_id) ou None se o OpenWA nao responder."""
    try:
        chave = wa.ler_api_key(cfg_wa)
        sessao = wa.achar_sessao(cfg_wa, chave)
    except Exception as e:
        registrar("AVISO: nao consegui falar com o OpenWA para marcar no grupo ({}).".format(e))
        return None
    if not sessao:
        registrar("AVISO: nenhuma sessao do WhatsApp conectada; deixo a OS pendente.")
        return None
    return chave, sessao["id"]


def _mensagens_do_grupo(cfg_wa, chave, sessao_id, nome_grupo, registrar):
    gid = _CACHE.get("grupo")
    if not gid:
        gid = wa.chat_id_do_grupo(cfg_wa, chave, sessao_id, nome_grupo)
        if not gid:
            registrar("AVISO: grupo '{}' nao encontrado no WhatsApp.".format(nome_grupo))
            return None, None
        _CACHE["grupo"] = gid
    return gid, wa.mensagens_do_chat(cfg_wa, chave, sessao_id, [gid])


def _marcar_os(cfg_wa, chave, sessao_id, gid, msgs, os_num, registrar):
    """Reage em TODAS as mensagens do grupo com essa OS. True se marcou alguma.

    Todas, e nao so a mais recente, porque uma OS reaparece quando ha correcao
    ou regravacao e o pessoal quer ver as duas resolvidas. Reagir de novo com o
    mesmo emoji nao duplica nada no WhatsApp, entao nao vale gastar uma chamada
    por mensagem so para conferir se ja estava marcada.
    """
    alvos = [m for m in msgs if numero_da_os(m.get("body")) == os_num]
    if not alvos:
        return False
    marcadas = 0
    for m in alvos:
        wid = m.get("waMessageId")
        if not wid:
            continue
        try:
            wa.reagir(cfg_wa, chave, sessao_id, gid, wid)
            marcadas += 1
        except Exception as e:
            registrar("AVISO: nao consegui marcar a OS {} no grupo ({}).".format(os_num, e))
    if marcadas:
        registrar("    OS {} marcada no grupo do WhatsApp ({} mensagem(ns)).".format(os_num, marcadas))
    return marcadas > 0


def processar(cfg, nomes_baixados, registrar):
    """Marca no grupo as OS dos arquivos recem-baixados e cuida das pendentes.

    Chamada a cada passada do vigia do Teams, mesmo sem arquivo novo: as OS que
    ficaram pendentes precisam ser tentadas de novo.
    """
    if not cfg.get("marcar_no_grupo_whatsapp", False):
        return

    pendentes = ler_pendencias()
    agora = time.time()

    # OS novas entram na fila; quem ja estava la mantem a hora original, senao
    # o prazo de aviso nunca venceria
    for nome in nomes_baixados or []:
        os_num = numero_da_os(nome)
        if not os_num:
            registrar("AVISO: '{}' nao comeca com numero de OS; nao da para marcar no grupo.".format(nome))
            continue
        if os_num not in pendentes:
            pendentes[os_num] = {"arquivo": nome, "desde": agora, "avisado": False}

    if not pendentes:
        return

    try:
        cfg_wa = wa.ler_config()
    except SystemExit:
        registrar("AVISO: config.json do WhatsApp nao encontrado; nao da para marcar no grupo.")
        return

    ligado = _conectar(cfg_wa, registrar)
    if not ligado:
        gravar_pendencias(pendentes)
        return
    chave, sessao_id = ligado

    nome_grupo = cfg.get("nome_do_grupo_whatsapp") or "Solida-CTP-Finart"
    try:
        gid, msgs = _mensagens_do_grupo(cfg_wa, chave, sessao_id, nome_grupo, registrar)
    except Exception as e:
        registrar("AVISO: nao consegui ler o grupo do WhatsApp ({}).".format(e))
        gravar_pendencias(pendentes)
        return
    if not gid:
        gravar_pendencias(pendentes)
        return

    prazo = float(cfg.get("minutos_para_avisar_pendencia", 5)) * 60
    limite = float(cfg.get("horas_para_desistir_da_os", 24)) * 3600
    sobraram = {}

    for os_num, info in pendentes.items():
        if _marcar_os(cfg_wa, chave, sessao_id, gid, msgs, os_num, registrar):
            continue
        idade = agora - info.get("desde", agora)
        if idade > limite:
            registrar("Desisto de marcar a OS {} ({}): passou de {:g}h sem mensagem no grupo.".format(
                os_num, info.get("arquivo"), limite / 3600))
            continue
        if idade > prazo and not info.get("avisado"):
            # aviso uma vez so: a cada passada repetiria o alerta a cada minuto
            info["avisado"] = True
            registrar("PENDENCIA  >>  OS {} baixada ha {:.0f} min e ainda sem mensagem no grupo.".format(
                os_num, idade / 60))
            registrar("    Arquivo: {}".format(info.get("arquivo")))
        sobraram[os_num] = info

    gravar_pendencias(sobraram)

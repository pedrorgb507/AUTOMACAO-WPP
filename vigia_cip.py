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
    4. move para a subpasta ENVIADOS e anota a entrega em ja_enviados_cip.json

Toda passada ele confere a pasta ENVIADOS: .ppf que esteja la sem o robo ter
entregue vira aviso no log. Sem isso, arquivo movido para ENVIADOS por fora
nunca mais e olhado - foi assim que tres chapas da Solida nao chegaram em 22/09.

O envio para a Solida vai pelo navegador (teams_web.py), nao pelo Graph. O
chat dela e de conta pessoal, e mandar por ali dispensa subir o arquivo para o
OneDrive e liberar leitura para o cliente: a sessao logada resolve a permissao,
igual a quando a gente anexa na mao. Quem manda por WhatsApp segue pelo OpenWA.

O login do navegador e o mesmo do robo que baixa: tarefa "Teams: refazer login".

Uso:
    python vigia_cip.py            uma passada
    python vigia_cip.py --vigiar   fica rodando
    python vigia_cip.py --teste    mostra o que faria, sem enviar nem mover
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

import painel
import pastas
import teams_web as tw


AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config_cip.json")
LOG = os.path.join(AQUI, "vigia_cip.log")


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
    if not cfg.get("pastas"):
        registrar("ERRO: nenhuma pasta configurada em 'pastas' no config_cip.json.")
        sys.exit(1)
    for e in cfg["pastas"]:
        # 'teams' identifica a conversa pelo nome que aparece no Teams, porque
        # o robo clica nela como a gente faz; 'whatsapp' segue por chat_id.
        obrigatorios = ("pasta", "destino", "conversa") if e.get("destino") == "teams" \
            else ("pasta", "destino", "chat_id")
        for campo in obrigatorios:
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

    Procura cada nome nas pastas ENVIADOS das entradas que vao para o Teams.
    Diferente da versao antiga, nao ha item guardado no OneDrive para
    reaproveitar: o arquivo do disco e mandado de novo, e so.
    """
    entradas = [e for e in cfg["pastas"] if e["destino"] == "teams"]
    if not entradas:
        registrar("ERRO: nenhuma pasta com destino 'teams' no config_cip.json.")
        return 0

    sessao = tw.SessaoNavegador()
    feitos = 0
    try:
        for nome in nomes:
            entrada, caminho = None, None
            for e in entradas:
                tentativa = os.path.join(
                    e["pasta"], e.get("subpasta_enviados") or "ENVIADOS", nome)
                if os.path.isfile(tentativa):
                    entrada, caminho = e, tentativa
                    break
            if not caminho:
                registrar("ERRO: '{}' nao esta em nenhuma pasta ENVIADOS.".format(nome))
                continue
            try:
                sessao.enviar(entrada["conversa"], caminho, nome,
                              (entrada.get("mensagem") or "").strip())
            except Exception as e:
                registrar("ERRO ao reenviar '{}': {}".format(nome, e))
                continue
            anotar_entrega(entrada, nome)
            registrar("REENVIADO  >>  {}  (para '{}')".format(nome, entrada["conversa"]))
            feitos += 1
    finally:
        sessao.fechar()
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


REGISTRO_ENVIOS = os.path.join(AQUI, "ja_enviados_cip.json")

# 'entregues' e so trilha de auditoria ("quando mandei isso?"), entao tem teto.
# 'conhecidos' NAO pode ter teto: e ele que decide se um arquivo e estranho, e
# cortar o mais antigo faria o robo redescobrir chapa velha como se fosse orfa.
MAX_ENTREGAS = 800

# Data da ultima vez que olhei cada pasta ENVIADOS. Fica na memoria, nao no
# disco, de proposito: assim o robo relista ao subir, e pega o que tenham
# movido para la enquanto ele estava fora do ar - que e justamente o caso que
# este conserto existe para cobrir.
ULTIMA_MARCA = {}


def _chave(entrada, nome):
    return "{}|{}".format(rotulo(entrada), nome)


def ler_envios():
    """Registro do que ESTE robo entregou. Registro ilegivel vira registro novo."""
    try:
        with open(REGISTRO_ENVIOS, encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        reg = None
    if not isinstance(reg, dict):
        reg = {}
    reg.setdefault("conhecidos", [])  # tudo que ja foi contabilizado em ENVIADOS
    reg.setdefault("entregues", {})   # chave -> quando (auditoria, com teto)
    reg.setdefault("baseado", [])     # pastas cujo conteudo antigo ja foi aceito
    return reg


def gravar_envios(reg):
    ent = reg.get("entregues") or {}
    if len(ent) > MAX_ENTREGAS:
        reg["entregues"] = dict(sorted(ent.items(), key=lambda kv: kv[1])[-MAX_ENTREGAS:])
    try:
        with open(REGISTRO_ENVIOS, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2, ensure_ascii=False)
    except OSError as e:
        # nao derruba a passada: perder o registro atrasa a conferencia, mas
        # deixar de mandar chapa por causa disso seria trocar um problema
        # pequeno por um grande.
        registrar("AVISO: nao consegui gravar {} ({}).".format(
            os.path.basename(REGISTRO_ENVIOS), e))


def anotar_entrega(entrada, nome):
    """Anota que o robo entregou este arquivo, para ele nao virar 'estranho'."""
    reg = ler_envios()
    chave = _chave(entrada, nome)
    reg["entregues"][chave] = dt.datetime.now().isoformat(timespec="seconds")
    if chave not in reg["conhecidos"]:
        reg["conhecidos"].append(chave)
    gravar_envios(reg)


def conferir_enviados(entrada):
    """Avisa se aparecer em ENVIADOS um arquivo que este robo nao entregou.

    Arquivo em ENVIADOS e dado por resolvido e nunca mais olhado. Entao um .ppf
    arrastado para la sem ter sido mandado some do radar em silencio, e ninguem
    descobre ate o cliente cobrar. Foi o que aconteceu em 22/09: o vigia ficou
    fora do ar das 09:10 as 14:24, o CTP gravou tres chapas da Solida nesse
    buraco e alguem as moveu para ENVIADOS - nenhuma chegou, e nenhum log
    acusou nada.

    Nao mando sozinho o que acho: reenviar por conta propria duplicaria chapa no
    chat do cliente se ela tiver sido mandada na mao. Aviso e deixo a decisao.
    """
    pasta = os.path.join(entrada["pasta"], entrada.get("subpasta_enviados") or "ENVIADOS")
    try:
        marca = os.path.getmtime(pasta)
    except OSError:
        return  # pasta fora do ar ou ainda sem ENVIADOS: o resto da passada avisa

    # Listar ENVIADOS toda passada custa caro: e pasta de rede com milhares de
    # arquivos, e o \servidor trava por minutos sem aviso. A data da pasta muda
    # sempre que alguem poe algo nela - que e exatamente o sinal que interessa.
    chave_pasta = rotulo(entrada)
    if ULTIMA_MARCA.get(chave_pasta) == marca:
        return

    aceitas = [e.lower() for e in (entrada.get("extensoes_aceitas") or [])]
    try:
        nomes = [n for n in sorted(os.listdir(pasta))
                 if os.path.isfile(os.path.join(pasta, n))
                 and not (aceitas and os.path.splitext(n)[1].lower() not in aceitas)]
    except OSError:
        return

    reg = ler_envios()
    conhecidos = set(reg["conhecidos"])
    estranhos = [n for n in nomes if _chave(entrada, n) not in conhecidos]

    if chave_pasta not in reg["baseado"]:
        # Primeira vez nesta pasta: o que ja estava la e de antes do registro
        # existir, e nao da para saber se foi entregue. Acusar tudo seria um
        # alarme de milhares de linhas que ninguem le - e alarme que ninguem le
        # e pior que alarme nenhum.
        reg["baseado"].append(chave_pasta)
        registrar("Registro de entregas criado para '{}': tomei os {} arquivo(s) que ja"
                  " estavam em ENVIADOS como conhecidos. Daqui para frente, .ppf que"
                  " aparecer la sem eu ter mandado vira aviso.".format(
                      chave_pasta, len(estranhos)))
    else:
        for n in estranhos:
            registrar("ATENCAO: '{}' esta em ENVIADOS mas eu nunca mandei ({})."
                      " Se o cliente nao recebeu, mova de volta para {} que eu mando"
                      " na proxima passada.".format(n, chave_pasta, entrada["pasta"]))

    # Contabilizados (avisados ou aceitos no baseline), para nao repetir o
    # alarme a cada passada.
    reg["conhecidos"].extend(_chave(entrada, n) for n in estranhos)
    gravar_envios(reg)
    ULTIMA_MARCA[chave_pasta] = marca


ULTIMO_ESTADO = {}


def avisar_estado(chave, texto):
    """Registra so quando muda. A chave separa o estado de cada pasta, senao
    duas pastas ficariam se sobrescrevendo e repetindo aviso a cada passada."""
    if ULTIMO_ESTADO.get(chave) != texto:
        ULTIMO_ESTADO[chave] = texto
        registrar(texto)


def processar_pasta(cfg, entrada, sessao, modo_teste):
    """Envia tudo que estiver na pasta dessa entrada. Devolve quantos sairam."""
    nome_pasta = rotulo(entrada)

    # 'ativo': false pausa a pasta sem apagar a configuracao. Avisa uma vez a
    # cada mudanca de estado: pausa silenciosa e pausa esquecida.
    if not entrada.get("ativo", True):
        avisar_estado(nome_pasta, "PAUSADO: '{}' nao esta enviando (ativo=false no config_cip.json).".format(
            nome_pasta))
        return 0

    conferir_enviados(entrada)

    arquivos = arquivos_da_pasta(entrada)
    if arquivos is None:
        avisar_estado(nome_pasta, "Pasta inacessivel: {}. Tento de novo.".format(entrada["pasta"]))
        return 0
    if not arquivos:
        avisar_estado(nome_pasta, "Vigiando {}. Aguardando arquivos...".format(entrada["pasta"]))
        return 0

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
                novo_nome, entrada["destino"],
                entrada.get("conversa") or entrada.get("nome_do_chat") or entrada.get("chat_id")))
            continue

        if not arquivo_estavel(caminho, espera):
            registrar("'{}' ainda esta sendo gravado; deixo para a proxima passada.".format(nome))
            continue

        try:
            if entrada["destino"] == "teams":
                sessao.enviar(entrada["conversa"], caminho, novo_nome,
                              (entrada.get("mensagem") or "").strip())
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

        anotar_entrega(entrada, novo_nome)

        # So chega aqui depois do envio confirmado E do arquivo sair da fila:
        # o bloco diz ENVIADO porque as duas coisas ja aconteceram.
        painel.bloco(LOG, nome_pasta, [
            ("CIP", novo_nome),
            ("DE", nome if novo_nome != nome else None),
            ("ENVIADO", ""),
            ("ARQUIVADO EM", destino),
        ])
        feitos += 1
    return feitos


def uma_passada(cfg, modo_teste=False, sessao=None):
    """Envia o que estiver nas pastas. Devolve quantos sairam.

    'sessao' emprestada: quando quem chama ja tem uma janela de navegador
    aberta, usa-se a dela e NAO se fecha no fim - fechar a janela de outro
    derrubaria o trabalho dele. Sem emprestimo, abre a sua e fecha.
    """
    total = 0
    minha = sessao is None
    # So abre navegador se alguma pasta precisar: quem so manda por WhatsApp
    # nunca paga o custo de abrir o Chrome.
    if minha:
        sessao = tw.SessaoNavegador(visivel=bool(cfg.get("mostrar_navegador", False)))
    try:
        for entrada in cfg["pastas"]:
            try:
                total += processar_pasta(cfg, entrada, sessao, modo_teste)
            except Exception as e:
                registrar("ERRO na pasta '{}': {}".format(rotulo(entrada), e))
    finally:
        if minha:
            sessao.fechar()
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
    p.add_argument("--reenviar", nargs="+", metavar="ARQUIVO",
                   help="manda de novo arquivos que ja estao em ENVIADOS")
    args = p.parse_args()

    cfg = ler_config()
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

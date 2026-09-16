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

O envio para a Solida vai pelo navegador (teams_web.py), nao pelo Graph. O
chat dela e de conta pessoal, e mandar por ali dispensa subir o arquivo para o
OneDrive e liberar leitura para o cliente: a sessao logada resolve a permissao,
igual a quando a gente anexa na mao. Quem manda por WhatsApp segue pelo OpenWA.

O login do navegador e o mesmo do robo que baixa: TEAMS-WEB-LOGIN.bat.

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

import shutil
import tempfile

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

class SessaoNavegador(object):
    """Mantem UMA janela de navegador para a passada inteira.

    Abrir o navegador custa dezenas de segundos. Abrir um por arquivo deixaria
    a passada lenta a ponto de atrasar o CTP, entao abre-se na primeira vez que
    alguma pasta precisar e reaproveita-se ate o fim da passada.
    """

    def __init__(self):
        self._pw = None
        self._ctx = None
        self._pg = None
        self._conversa_aberta = None

    def pagina(self):
        if self._pg is not None:
            return self._pg
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._ctx = tw.abrir(self._pw, visivel=False)
        self._pg = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._pg.goto(tw.TEAMS, timeout=120000)
        self._pg.wait_for_timeout(18000)
        if not tw.esta_logado(self._pg):
            raise RuntimeError("a sessao do Teams caiu - rode TEAMS-WEB-LOGIN.bat")
        return self._pg

    def enviar(self, conversa, caminho, nome, texto):
        """Manda o arquivo na conversa, com o nome ja limpo."""
        pg = self.pagina()
        if self._conversa_aberta != conversa:
            if not tw.abrir_conversa(pg, conversa):
                raise RuntimeError("nao consegui abrir a conversa '{}'".format(conversa))
            self._conversa_aberta = conversa

        # O arquivo vai para o Teams com o nome que o navegador ler do disco,
        # entao renomear so na variavel nao bastaria: manda-se uma copia com o
        # nome certo, numa pasta temporaria que some no fim.
        temporaria = tempfile.mkdtemp(prefix="cip-")
        try:
            copia = os.path.join(temporaria, nome)
            shutil.copy2(caminho, copia)
            if not tw.enviar_arquivo(pg, copia, texto or None):
                # nao sei em que estado a caixa ficou; forca reabrir a conversa
                self._conversa_aberta = None
                raise RuntimeError("o envio de '{}' nao se confirmou".format(nome))
        finally:
            shutil.rmtree(temporaria, ignore_errors=True)

    def fechar(self):
        for fechar in (getattr(self._ctx, "close", None), getattr(self._pw, "stop", None)):
            try:
                if fechar:
                    fechar()
            except Exception:
                pass
        self._pw = self._ctx = self._pg = None
        self._conversa_aberta = None


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

    sessao = SessaoNavegador()
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

        registrar("ENVIADO  >>  {}  ({})".format(novo_nome, nome_pasta))
        if novo_nome != nome:
            registrar("    de: {}".format(nome))
        registrar("    arquivado em: {}".format(destino))
        feitos += 1
    return feitos


def uma_passada(cfg, modo_teste=False):
    total = 0
    # Uma janela de navegador para a passada inteira. So abre se alguma pasta
    # com destino 'teams' tiver arquivo para mandar - quem so usa WhatsApp
    # nunca paga o custo de abrir.
    sessao = SessaoNavegador()
    try:
        for entrada in cfg["pastas"]:
            try:
                total += processar_pasta(cfg, entrada, sessao, modo_teste)
            except Exception as e:
                registrar("ERRO na pasta '{}': {}".format(rotulo(entrada), e))
    finally:
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

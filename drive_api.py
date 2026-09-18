# -*- coding: utf-8 -*-
"""
DRIVE API - baixa do Google Drive os arquivos que chegam por link no e-mail.

Existe porque o Gmail troca o anexo por um link do Drive quando o arquivo e
grande. O e-mail chega sem anexo nenhum, e o vigia - que so sabia pegar anexo
de verdade - dava o e-mail por tratado e seguia calado. Arquivos da Viva se
perderam assim, sem erro no log, que e o que torna essa falha cara.

Por que API e nao navegador: o link nao e publico, vem compartilhado com a
nossa conta, entao baixar exige estar logado. A senha de aplicativo do
config_email.json nao alcanca - ela vale para IMAP, nao para o Drive. E entrar
na conta por um navegador automatizado o Google recusa na cara ("Esse navegador
ou app pode nao ser seguro"), o que foi testado e confirmado. A API e o caminho
que o Google oferece de proposito: o login acontece uma vez no SEU navegador
normal, e depois o robo renova o acesso sozinho, sem navegador nenhum.

Primeira vez (uma so):
    1. Crie a credencial no Google Cloud Console - o passo a passo esta no
       LEIA-ME, secao "Ligar o Drive na primeira vez".
    2. Salve o arquivo baixado como credenciais_drive.json aqui nesta pasta.
    3. Rode a tarefa "Drive: refazer login do Google" (Ctrl+Shift+P, Tasks: Run Task) e autorize na janela que abrir.

Uso:
    python drive_api.py --login        autoriza a conta (abre o seu navegador)
    python drive_api.py --testar ID    baixa um arquivo pelo id, para conferir
"""

import argparse
import datetime as dt
import io
import os
import sys

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    print("Faltam bibliotecas do Google. Rode o INSTALAR-BIBLIOTECAS.bat ou:")
    print("    python -m pip install --user google-api-python-client"
          " google-auth-httplib2 google-auth-oauthlib")
    sys.exit(1)


AQUI = os.path.dirname(os.path.abspath(__file__))
CREDENCIAIS = os.path.join(AQUI, "credenciais_drive.json")
TOKEN = os.path.join(AQUI, "token_drive.json")
LOG = os.path.join(AQUI, "vigia_email.log")   # mesmo log do vigia que o usa

# So leitura: o robo nunca precisa escrever nem apagar nada no Drive de
# ninguem, entao nao se pede permissao para isso.
ESCOPOS = ["https://www.googleapis.com/auth/drive.readonly"]


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


def credenciais(interativo=False, forcar=False):
    """Devolve a autorizacao da conta, renovando sozinha quando vence.

    O token vence toda hora, mas vem com um 'refresh token' que o renova sem
    ninguem digitar nada - e por isso que o login e uma vez so. Se ate o
    refresh falhar (senha trocada, acesso revogado), so um login novo resolve,
    e ai e preciso alguem na frente do computador.
    """
    # 'forcar' existe por causa de um caso concreto: publicar o app no Google nao
    # renova o acesso que ja esta na maquina. Um token emitido enquanto a tela de
    # permissao estava em "Teste" carrega o prazo de 7 dias CONSIGO, e reaproveita-lo
    # faz o login dizer "AUTORIZADO" sem ter autorizado nada - o prazo segue correndo
    # e ninguem descobre ate ele vencer.
    cred = None
    if forcar:
        cred = None
    elif os.path.exists(TOKEN):
        try:
            cred = Credentials.from_authorized_user_file(TOKEN, ESCOPOS)
        except Exception:
            cred = None

    if cred and cred.valid:
        return cred

    if cred and cred.expired and cred.refresh_token:
        try:
            cred.refresh(Request())
            _guardar(cred)
            return cred
        except Exception as e:
            registrar("AVISO: nao consegui renovar o acesso ao Drive ({}).".format(str(e)[:80]))
            cred = None

    if not interativo:
        raise RuntimeError(
            "sem autorizacao do Drive - rode a tarefa 'Drive: refazer login do Google'")

    if not os.path.exists(CREDENCIAIS):
        raise RuntimeError(
            "falta o arquivo credenciais_drive.json nesta pasta. Veja no LEIA-ME"
            " a secao 'Ligar o Drive na primeira vez'.")

    fluxo = InstalledAppFlow.from_client_secrets_file(CREDENCIAIS, ESCOPOS)
    # Abre o SEU navegador, nao um automatizado - e por isso que o Google
    # aceita este login e recusava o outro.
    cred = fluxo.run_local_server(port=0, prompt="consent",
                                  authorization_prompt_message="Abrindo o navegador para voce autorizar...",
                                  success_message="Pronto! Pode fechar esta aba e voltar ao terminal.")
    _guardar(cred)
    return cred


def _guardar(cred):
    try:
        with open(TOKEN, "w", encoding="utf-8") as f:
            f.write(cred.to_json())
    except OSError as e:
        registrar("AVISO: nao consegui guardar o token do Drive ({}).".format(e))


class SessaoDrive(object):
    """Acesso ao Drive reaproveitado durante a passada.

    Montar o cliente custa uma chamada de rede; a maioria dos e-mails nem tem
    link do Drive, entao ele so nasce quando o primeiro link aparece.
    """

    def __init__(self, visivel=False):   # 'visivel' existe so para manter a
        self._servico = None             # mesma forma de quem chamava antes

    def servico(self):
        if self._servico is None:
            self._servico = build("drive", "v3", credentials=credenciais(),
                                  cache_discovery=False)
        return self._servico

    def baixar(self, id_arquivo):
        """Baixa o arquivo pelo id e devolve (nome, bytes).

        Devolve bytes para o link do Drive entrar no vigia pelo mesmo caminho
        de um anexo comum - assim o resto do codigo nao precisa saber de onde
        o arquivo veio.
        """
        svc = self.servico()
        info = svc.files().get(fileId=id_arquivo,
                               fields="name,size,mimeType",
                               supportsAllDrives=True).execute()
        nome = info.get("name") or id_arquivo

        buffer = io.BytesIO()
        baixador = MediaIoBaseDownload(
            buffer, svc.files().get_media(fileId=id_arquivo, supportsAllDrives=True),
            chunksize=8 * 1024 * 1024)
        pronto = False
        while not pronto:
            _, pronto = baixador.next_chunk()

        dados = buffer.getvalue()
        if not dados:
            raise RuntimeError("o Drive devolveu o arquivo vazio")
        esperado = int(info.get("size") or 0)
        if esperado and len(dados) != esperado:
            # confere o tamanho porque arquivo pela metade e pior que arquivo
            # nenhum: ele parece pronto na pasta do cliente
            raise RuntimeError("baixou {} bytes mas o Drive diz que sao {}".format(
                len(dados), esperado))
        return nome, dados

    def fechar(self):
        self._servico = None


def main():
    ap = argparse.ArgumentParser(description="Baixa do Google Drive pela API oficial.")
    ap.add_argument("--login", action="store_true", help="autoriza a conta (abre o seu navegador)")
    ap.add_argument("--testar", metavar="ID", help="baixa um arquivo pelo id e diz o tamanho")
    a = ap.parse_args()
    if a.login:
        try:
            credenciais(interativo=True, forcar=True)
            registrar("AUTORIZADO. O acesso fica guardado em token_drive.json.")
            registrar("Nao precisa repetir: o robo renova sozinho daqui para frente.")
        except Exception as e:
            registrar("ERRO no login: {}".format(e))
            sys.exit(1)
    elif a.testar:
        s = SessaoDrive()
        nome, dados = s.baixar(a.testar)
        registrar("OK: '{}' com {:.2f} MB".format(nome, len(dados) / 1048576))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

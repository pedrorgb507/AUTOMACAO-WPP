# -*- coding: utf-8 -*-
"""
DRIVE WEB - baixa arquivo do Google Drive usando um navegador logado.

Existe porque o Gmail troca o anexo por um link do Drive quando o arquivo e
grande. O e-mail chega sem anexo nenhum, e o vigia - que so sabia pegar anexo
de verdade - dava o e-mail por tratado e seguia calado. Foi assim que arquivos
da Viva passaram batido sem ninguem notar.

O link nao e publico: vem compartilhado com a nossa conta. Baixar sem estar
logado cai na tela de login, e a senha de aplicativo do Gmail nao ajuda - ela
vale para IMAP, nao para o Drive. Por isso aqui e a mesma receita do robo do
Teams: um navegador com a sessao guardada num perfil proprio.

O login fica em perfil_drive_web, separado do seu Chrome do dia a dia.

Uso:
    python drive_web.py --login        abre o navegador para voce entrar
    python drive_web.py --testar ID    baixa um arquivo pelo id, para conferir
"""

import argparse
import datetime as dt
import os
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Falta o Playwright. Rode:  python -m pip install playwright")
    sys.exit(1)


AQUI = os.path.dirname(os.path.abspath(__file__))
PERFIL = os.path.join(AQUI, "perfil_drive_web")
LOG = os.path.join(AQUI, "vigia_email.log")   # mesmo log do vigia que o usa

DRIVE = "https://drive.google.com/drive/my-drive"

# Endereco que entrega o arquivo direto, sem passar pela tela de visualizacao.
# Arquivo grande cai antes numa pagina de aviso do antivirus, tratada abaixo.
BAIXAR = "https://drive.usercontent.google.com/download?id={}&export=download"


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


def abrir(p, visivel):
    os.makedirs(PERFIL, exist_ok=True)
    return p.chromium.launch_persistent_context(
        PERFIL, channel="chrome", headless=not visivel,
        args=["--no-first-run", "--no-default-browser-check"],
        accept_downloads=True, viewport={"width": 1400, "height": 950})


def esta_logado(pg):
    """True so quando a conta esta logada de verdade no Drive.

    Olhar so a URL nao serve: a pagina de login tambem mora em google.com e
    redireciona para o Drive depois. Aqui se exige que nao seja tela de login.
    """
    url = (pg.url or "").lower()
    if any(x in url for x in ("accounts.google.com", "/signin", "servicelogin")):
        return False
    return "drive.google.com" in url or "docs.google.com" in url


def login():
    registrar("Abrindo o navegador do Drive.")
    registrar("ENTRE NA CONTA que recebe os e-mails (a mesma do vigia).")
    registrar("Eu aviso aqui quando reconhecer o Drive carregado - nao feche antes.")
    with sync_playwright() as p:
        ctx = abrir(p, visivel=True)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            pg.goto(DRIVE, timeout=120000)
        except Exception as e:
            registrar("nao consegui abrir a pagina: {}".format(str(e)[:90]))
        limite = dt.datetime.now() + dt.timedelta(minutes=15)
        aviso = dt.datetime.now()
        while dt.datetime.now() < limite:
            try:
                if esta_logado(pg):
                    pg.wait_for_timeout(5000)
                    if esta_logado(pg):
                        registrar("LOGIN CONFIRMADO. Sessao guardada em: {}".format(PERFIL))
                        pg.wait_for_timeout(2000)
                        ctx.close()
                        return True
            except Exception:
                pass
            if (dt.datetime.now() - aviso).total_seconds() > 20:
                aviso = dt.datetime.now()
                registrar("   ...ainda esperando o login.")
            pg.wait_for_timeout(3000)
        registrar("Passaram 15 minutos sem reconhecer o Drive logado.")
        ctx.close()
        return False


class SessaoDrive(object):
    """Uma janela de navegador emprestada para varios downloads da passada.

    Abrir o Chrome custa dezenas de segundos e a maioria dos e-mails nem tem
    link do Drive. Por isso a janela so nasce quando o primeiro link aparece,
    e depois atende os outros da mesma passada.
    """

    def __init__(self, visivel=False):
        self.visivel = visivel
        self._pw = None
        self._ctx = None
        self._pg = None

    def pagina(self):
        if self._pg is not None:
            return self._pg
        self._pw = sync_playwright().start()
        try:
            self._ctx = abrir(self._pw, visivel=self.visivel)
        except Exception as e:
            self.fechar()
            raise RuntimeError(
                "nao consegui abrir o navegador do Drive ({}). O perfil aceita um dono "
                "so: veja se sobrou um Chrome do robo aberto.".format(
                    str(e).splitlines()[0][:80]))
        self._pg = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._pg.goto(DRIVE, timeout=120000)
        self._pg.wait_for_timeout(4000)
        if not esta_logado(self._pg):
            self.fechar()
            raise RuntimeError("a sessao do Drive caiu - rode GMAIL-LOGIN.bat e entre na conta")
        return self._pg

    def baixar(self, id_arquivo, segundos=900):
        """Baixa o arquivo pelo id e devolve (nome, bytes).

        Devolve bytes para o link do Drive entrar no vigia pelo mesmo caminho
        de um anexo comum - assim o resto do codigo nao precisa saber de onde
        o arquivo veio.
        """
        pg = self.pagina()
        alvo = BAIXAR.format(id_arquivo)
        baixado = self._tentar(pg, alvo, segundos)
        if baixado is None:
            # Arquivo grande nao baixa direto: o Drive mostra antes um aviso de
            # que nao conseguiu verificar virus, com um botao de confirmar.
            baixado = self._confirmar(pg, segundos)
        if baixado is None:
            raise RuntimeError("o Drive nao entregou o arquivo (nem direto nem apos confirmar)")

        nome = baixado.suggested_filename
        # Grava primeiro em disco local: quem chama decide onde vai ficar, e a
        # pasta do cliente costuma ser de rede, que engasga.
        import tempfile
        temporaria = tempfile.mkdtemp(prefix="drive-")
        try:
            local = os.path.join(temporaria, nome)
            baixado.save_as(local)
            with open(local, "rb") as f:
                dados = f.read()
        finally:
            import shutil
            shutil.rmtree(temporaria, ignore_errors=True)
        if not dados:
            raise RuntimeError("o arquivo baixado veio vazio")
        return nome, dados

    def _tentar(self, pg, url, segundos):
        try:
            with pg.expect_download(timeout=segundos * 1000) as info:
                try:
                    pg.goto(url, timeout=60000)
                except Exception:
                    # virar download aborta a navegacao; nao e erro
                    pass
            return info.value
        except Exception:
            return None

    def _confirmar(self, pg, segundos):
        """Clica no 'baixar mesmo assim' da tela de aviso do antivirus."""
        alvos = ('form#download-form button', 'form#download-form input[type="submit"]',
                 '#uc-download-link', 'button:has-text("Fazer download mesmo assim")',
                 'button:has-text("Download anyway")')
        for sel in alvos:
            try:
                botao = pg.locator(sel).first
                if not botao.count():
                    continue
                with pg.expect_download(timeout=segundos * 1000) as info:
                    botao.click(timeout=20000)
                return info.value
            except Exception:
                continue
        return None

    def fechar(self):
        for encerrar in (getattr(self._ctx, "close", None), getattr(self._pw, "stop", None)):
            try:
                if encerrar:
                    encerrar()
            except Exception:
                pass
        self._pw = self._ctx = self._pg = None


def main():
    ap = argparse.ArgumentParser(description="Baixa arquivo do Drive com navegador logado.")
    ap.add_argument("--login", action="store_true", help="abre o navegador para entrar na conta")
    ap.add_argument("--testar", metavar="ID", help="baixa um arquivo pelo id e diz o tamanho")
    a = ap.parse_args()
    if a.login:
        login()
    elif a.testar:
        s = SessaoDrive()
        try:
            nome, dados = s.baixar(a.testar)
            registrar("OK: '{}' com {:.2f} MB".format(nome, len(dados) / 1048576))
        finally:
            s.fechar()
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

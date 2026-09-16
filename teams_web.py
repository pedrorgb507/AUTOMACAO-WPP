# -*- coding: utf-8 -*-
"""
TEAMS WEB - robo de navegador para baixar anexos do Teams de conta PESSOAL.

Existe porque a API do Graph nao alcanca arquivo que mora em OneDrive pessoal:
quando a Solida manda pelo chat da conta dela, o token corporativo da Finart
leva 401/403. Um navegador logado baixa normalmente, porque a sessao do usuario
resolve a permissao - e o mesmo que clicar em baixar na mao.

O login fica guardado num perfil de navegador proprio (pasta perfil_teams_web),
separado do seu Chrome do dia a dia.

Uso:
    python teams_web.py --login    abre o navegador para voce entrar na conta
    python teams_web.py --ver      mostra o que o robo enxerga (sem baixar)
"""

import argparse
import datetime as dt
import json
import os
import sys
import time

import pastas

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Falta o Playwright. Rode:  python -m pip install playwright")
    sys.exit(1)


AQUI = os.path.dirname(os.path.abspath(__file__))
PERFIL = os.path.join(AQUI, "perfil_teams_web")
LOG = os.path.join(AQUI, "teams_web.log")

# Teams de conta pessoal fica neste endereco; o teams.microsoft.com e o corporativo
TEAMS = "https://teams.live.com/"


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
    """Abre o Chrome com o perfil do robo. O perfil guarda o login entre execucoes."""
    os.makedirs(PERFIL, exist_ok=True)
    return p.chromium.launch_persistent_context(
        PERFIL, channel="chrome", headless=not visivel,
        args=["--no-first-run", "--no-default-browser-check"],
        accept_downloads=True, viewport={"width": 1400, "height": 950})


# Textos que so aparecem na pagina de propaganda do Teams (antes do login).
# Sem checar isso, o robo achava que estava logado assim que a URL virava
# teams.live.com - que e o endereco da propaganda tambem.
MARCAS_DE_PROPAGANDA = (
    "baixar o aplicativo teams", "download the teams app",
    "reunioes gratuitas", "reuniões gratuitas", "free 60-minute",
    "recurso pago", "desbloqueie recursos de ia",
)

# Pedacos do app de verdade: se algum existir, estamos dentro.
# Descobertos olhando o DOM do Teams logado desta conta. Os nomes antigos
# (chat-list, app-bar) nao existem nesta versao - foi o que fez o robo achar
# que nunca logava.
MARCAS_DO_APP = (
    '[data-tid="chat-pane-item"]',      # cada conversa da lista
    '[data-tid="experience-layout"]',   # a casca do app
    '[data-tid="chat-pane-message"]',   # mensagens da conversa aberta
    '[data-tid="title-bar"]',
)


def esta_logado(pg):
    """True so quando a tela e o Teams de verdade, nao a propaganda nem o login."""
    url = (pg.url or "").lower()
    if any(x in url for x in ("login.live.com", "login.microsoftonline.com", "/signin")):
        return False
    if "teams.live.com" not in url and "teams.microsoft.com" not in url:
        return False
    try:
        texto = pg.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    if any(m in texto for m in MARCAS_DE_PROPAGANDA):
        return False
    for sel in MARCAS_DO_APP:
        try:
            if pg.locator(sel).count() > 0:
                return True
        except Exception:
            pass
    return False


def login():
    registrar("Abrindo o navegador.")
    registrar("ENTRE NA CONTA na janela que abriu. Pode demorar o quanto precisar.")
    registrar("Eu aviso aqui quando reconhecer o Teams carregado - nao feche a janela antes disso.")
    with sync_playwright() as p:
        ctx = abrir(p, visivel=True)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            pg.goto(TEAMS, timeout=120000)
        except Exception as e:
            registrar("nao consegui abrir a pagina: {}".format(e))
        limite = dt.datetime.now() + dt.timedelta(minutes=15)
        ultimo_aviso = dt.datetime.now()
        while dt.datetime.now() < limite:
            try:
                if esta_logado(pg):
                    # confirma duas vezes, com folga, para nao pegar tela intermediaria
                    pg.wait_for_timeout(6000)
                    if esta_logado(pg):
                        registrar("LOGIN CONFIRMADO. URL: {}".format(pg.url))
                        try:
                            pg.screenshot(path=os.path.join(AQUI, "teams_web_tela.png"))
                            registrar("print da tela salvo em teams_web_tela.png")
                        except Exception:
                            pass
                        registrar("Sessao guardada em: {}".format(PERFIL))
                        pg.wait_for_timeout(2000)
                        ctx.close()
                        return True
            except Exception:
                pass
            if (dt.datetime.now() - ultimo_aviso).total_seconds() > 20:
                ultimo_aviso = dt.datetime.now()
                registrar("   ...ainda esperando o login (a tela atual nao e o Teams logado).")
            pg.wait_for_timeout(3000)
        registrar("Passaram 15 minutos sem reconhecer o Teams logado. Feche e tente de novo.")
        ctx.close()
        return False


def ver():
    """Abre logado e conta o que consegue enxergar, para eu montar o resto em cima."""
    with sync_playwright() as p:
        ctx = abrir(p, visivel=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(TEAMS, timeout=120000)
        pg.wait_for_timeout(15000)
        registrar("URL final: {}".format(pg.url))
        registrar("logado? {}".format(esta_logado(pg)))
        registrar("titulo: {}".format(pg.title()))
        try:
            texto = pg.locator("body").inner_text(timeout=15000)
            registrar("--- primeiros 1500 caracteres da tela ---")
            for linha in texto[:1500].splitlines():
                if linha.strip():
                    registrar("   " + linha.strip()[:110])
        except Exception as e:
            registrar("nao consegui ler a tela: {}".format(e))
        try:
            pg.screenshot(path=os.path.join(AQUI, "teams_web_tela.png"), full_page=False)
            registrar("print salvo em teams_web_tela.png")
        except Exception:
            pass
        ctx.close()


def ler_config():
    caminho = os.path.join(AQUI, "config_teams_web.json")
    if not os.path.exists(caminho):
        registrar("ERRO: config_teams_web.json nao encontrado.")
        sys.exit(1)
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def vigiar(cfg):
    intervalo = int(cfg.get("segundos_entre_checagens", 60))
    registrar("Vigiando a conversa '{}' no Teams Web (a cada {}s). Feche a janela para parar.".format(
        cfg["conversa"], intervalo))
    while True:
        try:
            uma_passada(cfg)
        except KeyboardInterrupt:
            registrar("Encerrado pelo usuario.")
            return
        except Exception as e:
            registrar("ERRO inesperado: {}".format(str(e)[:150]))
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
    ap = argparse.ArgumentParser(description="Robo de navegador para o Teams de conta pessoal.")
    ap.add_argument("--login", action="store_true", help="abre o navegador para entrar na conta")
    ap.add_argument("--ver", action="store_true", help="mostra o que o robo enxerga")
    ap.add_argument("--teste", action="store_true", help="lista o que baixaria, sem baixar")
    ap.add_argument("--corte", action="store_true", help="marca o que ja esta na tela como tratado")
    ap.add_argument("--vigiar", action="store_true", help="fica rodando")
    a = ap.parse_args()
    if a.login:
        login()
    elif a.ver:
        ver()
    elif a.corte:
        semear_registro(ler_config())
    elif a.vigiar:
        vigiar(ler_config())
    elif a.teste:
        n = uma_passada(ler_config(), modo_teste=True)
    else:
        n = uma_passada(ler_config())
        registrar("{} arquivo(s) salvo(s).".format(n))


# ----------------------------------------------------------------------
# seletores do Teams (descobertos olhando o DOM logado - ver LEIA-ME)
# ----------------------------------------------------------------------

SEL_CONVERSA = '[role="treeitem"]'
SEL_MENSAGEM = '[data-tid="chat-pane-message"]'
SEL_ANEXO = '[data-tid^="file-chiclet-"]'
SEL_REAGIR = '[data-tid="add-reaction-picker-entry-point-button"]'
SEL_BAIXAR_ONEDRIVE = '[aria-label^="Baixar esse arquivo"]'

# Mensagem nossa tem esta classe; a do cliente nao. E o unico jeito confiavel
# de nao baixar de volta os proprios PPF que acabamos de enviar.
CLASSE_MINHA = "ChatMyMessage"

REGISTRO = os.path.join(AQUI, "ja_baixados_teams_web.json")


def ler_registro():
    try:
        with open(REGISTRO, "r", encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("baixados", [])
        return d
    except (OSError, ValueError):
        return {"baixados": []}


def gravar_registro(reg):
    reg["baixados"] = reg["baixados"][-4000:]
    try:
        with open(REGISTRO, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _sem_acento(t):
    """Compara nomes sem depender de acento nem de maiuscula."""
    import unicodedata
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def quem_esta_na_tela(pg):
    """Nomes de quem assina as mensagens da conversa aberta."""
    try:
        return pg.evaluate("""() => {
            const nomes = new Set();
            document.querySelectorAll('[data-tid="message-author-name"]').forEach(
                e => nomes.add((e.textContent || '').trim()));
            return [...nomes];
        }""")
    except Exception:
        return []


def ir_para_o_fim(pg):
    """Deixa a conversa nas mensagens mais recentes.

    Sem isto o Teams pode abrir a conversa parada num ponto antigo - e ai o robo
    le uma janela velha de mensagens, nao acha anexo nenhum e nao baixa nada,
    sem reclamar de coisa alguma. A lista e virtualizada: so o que esta perto da
    tela existe no DOM, entao nao adianta procurar por mensagem que ficou longe.
    """
    JS_ULTIMA = """() => {
        const m = document.querySelectorAll('[data-tid="chat-pane-message"]');
        return m.length ? m[m.length - 1].getAttribute('data-mid') : null;
    }"""
    try:
        # Rola com a roda em vez de clicar numa mensagem: se a ultima for um
        # anexo, o clique ABRE o arquivo no OneDrive em vez de rolar a lista.
        pg.mouse.move(900, 500)
        ultima, parado = None, 0
        for _ in range(30):
            pg.mouse.wheel(0, 5000)
            pg.wait_for_timeout(1100)
            agora = pg.evaluate(JS_ULTIMA)
            if agora and agora == ultima:
                parado += 1
                if parado >= 3:      # tres rodadas sem mudar: chegou no fim
                    break
            else:
                parado = 0
                ultima = agora
        pg.mouse.move(5, 5)          # tira a barra de hover da frente
        pg.wait_for_timeout(1500)
        if ultima:
            registrar("    fim da conversa: mensagem mais nova e de {}.".format(
                dt.datetime.fromtimestamp(int(ultima) / 1000).strftime("%d/%m/%Y %H:%M")))
    except Exception as e:
        registrar("AVISO: nao consegui ir para o fim da conversa ({}).".format(str(e)[:70]))


def _e_o_cliente(autores, nome):
    procurado = _sem_acento(nome)
    return any(procurado in _sem_acento(a) or _sem_acento(a) in procurado
               for a in autores if a)


def abrir_conversa(pg, nome):
    """Abre a conversa pelo nome e CONFERE que entrou na certa. True se conseguiu.

    Esperar um tempo fixo depois do clique nao serve: o Teams reabre sozinho na
    ultima conversa que esteve aberta, entao logo apos o clique a tela ainda
    pode ser a anterior - e o robo trabalharia na conversa de outro contato.
    Aqui se espera a conversa REALMENTE trocar, olhando quem assina as
    mensagens, e desiste em vez de chutar.
    """
    alvos = pg.locator(SEL_CONVERSA, has_text=nome)
    if not alvos.count():
        registrar("ERRO: nao achei a conversa '{}' na lista.".format(nome))
        return False
    alvos.first.click(timeout=20000)

    limite = time.time() + 45
    autores = []
    while time.time() < limite:
        pg.wait_for_timeout(2500)
        autores = quem_esta_na_tela(pg)
        if _e_o_cliente(autores, nome):
            ir_para_o_fim(pg)
            # ir para o fim carrega outras mensagens: confere de novo, porque
            # nao adianta ter entrado certo e terminar em outro lugar.
            if _e_o_cliente(quem_esta_na_tela(pg), nome):
                return True
            registrar("ERRO: a conversa mudou sozinha ao ir para o fim.")
            return False

    registrar("ERRO: cliquei em '{}' mas a conversa aberta e de: {}.".format(
        nome, ", ".join(autores) or "(ninguem identificado)"))
    registrar("    {} conversa(s) na lista casam com esse nome.".format(alvos.count()))
    registrar("    Nao vou mexer numa conversa que nao e a do cliente.")
    return False


def anexos_recebidos(pg):
    """[(data-mid, [nomes]), ...] das mensagens que o cliente mandou com anexo."""
    return pg.evaluate("""(marca) => {
        const saida = [];
        document.querySelectorAll('[data-tid="chat-pane-message"]').forEach(e => {
            if ((e.className||'').toString().includes(marca)) return;   // nossa, ignora
            const cs = [...e.querySelectorAll('[data-tid^="file-chiclet-"]')];
            if (!cs.length) return;
            saida.push({
                mid: e.getAttribute('data-mid'),
                nomes: cs.map(c => (c.getAttribute('data-tid')||'').replace('file-chiclet-',''))
            });
        });
        return saida;
    }""", CLASSE_MINHA)


def baixar_anexo(ctx, pg, mid, indice, pasta_destino):
    """Baixa um anexo: clicar abre o OneDrive em outra aba, e la tem o botao.

    Clicar direto no anexo nao baixa - so abre a previa. Foi preciso descobrir
    isso na mao; se um dia parar de funcionar, e aqui que quebra.
    """
    msg = pg.locator('[data-mid="{}"]'.format(mid))
    chiclet = msg.locator(SEL_ANEXO).nth(indice)
    aba = None
    try:
        with ctx.expect_page(timeout=40000) as nova:
            chiclet.click(timeout=15000)
        aba = nova.value
        aba.wait_for_load_state("domcontentloaded", timeout=60000)
        aba.wait_for_timeout(7000)
        botao = aba.locator(SEL_BAIXAR_ONEDRIVE).first
        if not botao.count():
            registrar("AVISO: nao achei o botao de baixar na aba do OneDrive.")
            return None
        with aba.expect_download(timeout=180000) as info:
            botao.click(timeout=20000)
        baixado = info.value
        nome = baixado.suggested_filename
        destino = pastas.nome_livre(pasta_destino, pastas.nome_seguro(nome))
        baixado.save_as(destino)
        return destino
    finally:
        if aba:
            try:
                aba.close()
            except Exception:
                pass


# Codigo do emoji no Teams. O visto e o 2705 (check verde); NAO confundir com
# o 2714 (check preto), que e outro emoji - e justamente o que aparece na grade
# do seletor. Procurar pelo emoji como texto tambem nao serve: os botoes sao
# rotulados em portugues ("Botao de marca de selecao") e nao contem o caractere.
COD_VISTO = "2705_whiteheavycheckmark"

# O visto mora na barra que aparece ao passar o mouse na mensagem, e NAO dentro
# do seletor de reacoes. Abrir o seletor era o que quebrava tudo: o painel
# cobre a barra e engole o clique. Por isso aqui nao se abre painel nenhum.
SEL_VISTO = '[data-tid="message-actions-{}"]'.format(COD_VISTO)

# Como se enxerga que a reacao existe: o Teams desenha uma "pilula" de resumo
# embaixo da mensagem, e ela so existe quando ha reacao de verdade. O emoji e
# reconhecido pelo itemid da imagem, que nao muda de idioma. O aria-pressed
# separa o que e nosso do que e do cliente - o + que a Solida poe nas nossas
# mensagens vem como false.
JS_TEM_VISTO = """([mid, cod]) => {
    const m = document.querySelector('[data-mid="' + mid + '"]');
    if (!m) return null;                       // rolou para fora / sumiu da tela
    const area = m.closest('.fui-ChatMessage, .fui-ChatMyMessage') || m;
    const img = area.querySelector(
        '[data-tid="diverse-reaction-pill-button"] img[itemid="' + cod + '"]');
    if (!img) return false;
    const pilula = img.closest('[data-tid="diverse-reaction-pill-button"]');
    return pilula.getAttribute('aria-pressed') === 'true';
}"""


def tem_visto(pg, mid):
    """True/False se o visto NOSSO ja esta na mensagem; None se ela sumiu da tela.

    None e diferente de False de proposito: "nao sei" nao pode virar "nao tem",
    senao o robo clica de novo numa mensagem ja marcada e TIRA o visto.
    """
    try:
        return pg.evaluate(JS_TEM_VISTO, [mid, COD_VISTO])
    except Exception:
        return None


def reagir(pg, mid):
    """Poe o visto na mensagem e confere se pegou de verdade.

    Devolve True so quando a pilula da reacao aparece depois do clique - e nao
    quando "o clique deu certo". Foi confiar no clique que fez a versao antiga
    jurar que tinha marcado sem ter marcado.

    O botao e liga/desliga: clicar numa mensagem ja marcada REMOVE o visto.
    Por isso a conferencia antes de clicar nao e economia, e seguranca.
    """
    ja = tem_visto(pg, mid)
    if ja:
        return True
    if ja is None:
        registrar("AVISO: nao consegui ver a mensagem {} para marcar.".format(mid))
        return False

    msg = pg.locator('[data-mid="{}"]'.format(mid))
    for tentativa in (1, 2):
        try:
            msg.scroll_into_view_if_needed(timeout=15000)
            msg.hover(timeout=10000)
            pg.wait_for_timeout(1500)
            # A barra as vezes e desenhada fora da mensagem; como acabamos de
            # passar o mouse nesta, a barra que estiver na tela e a dela.
            botao = msg.locator(SEL_VISTO).first
            if not botao.count():
                botao = pg.locator(SEL_VISTO).first
            if not botao.count():
                registrar("AVISO: o visto nao esta na barra rapida da mensagem {}.".format(mid))
                return False
            botao.click(timeout=10000)
            pg.wait_for_timeout(3000)
            pg.mouse.move(5, 5)        # tira a barra da frente antes de conferir
            pg.wait_for_timeout(1500)
            if tem_visto(pg, mid):
                return True
            registrar("AVISO: cliquei no visto da mensagem {} e ele nao apareceu"
                      " (tentativa {}).".format(mid, tentativa))
        except Exception as e:
            registrar("AVISO: erro ao marcar a mensagem {} ({}).".format(mid, str(e)[:70]))
            try:
                pg.keyboard.press("Escape")
            except Exception:
                pass
    return False


def uma_passada(cfg, modo_teste=False):
    """Baixa o que o cliente mandou de novo na conversa e marca com o visto."""
    reg = ler_registro()
    ja = set(reg["baixados"])
    salvos = 0
    with sync_playwright() as p:
        try:
            ctx = abrir(p, visivel=bool(cfg.get("mostrar_navegador", False)))
        except Exception as e:
            registrar("ERRO: nao consegui abrir o perfil do navegador ({}).".format(str(e)[:90]))
            registrar("    O Chrome do robo ainda esta aberto? Feche e tento de novo.")
            return 0
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(TEAMS, timeout=120000)
            pg.wait_for_timeout(int(cfg.get("segundos_carregar", 18)) * 1000)
            if not esta_logado(pg):
                registrar("SESSAO CAIU: o Teams pediu login de novo.")
                registrar("    Rode TEAMS-WEB-LOGIN.bat e entre na conta; ate la nada e baixado.")
                return 0
            if not abrir_conversa(pg, cfg["conversa"]):
                return 0

            # Rede de seguranca: a lista de mensagens e virtualizada e ja
            # aconteceu de a conversa abrir parada semanas atras. Sem este
            # limite, uma janela velha faria o robo baixar arquivo antigo -
            # e pior, guardar tudo na pasta de HOJE.
            dias = int(cfg.get("dias_para_tras", 3))
            cedo_demais = dt.datetime.now() - dt.timedelta(days=dias)
            velhas = 0

            for item in anexos_recebidos(pg):
                mid = item["mid"]
                quando = dt.datetime.fromtimestamp(int(mid) / 1000)
                if quando < cedo_demais:
                    velhas += 1
                    continue
                for i, nome in enumerate(item["nomes"]):
                    marca = "{}|{}".format(mid, nome)
                    if marca in ja:
                        continue
                    if modo_teste:
                        registrar("[TESTE] baixaria '{}' ({}, mensagem {})".format(
                            nome, quando.strftime("%d/%m %H:%M"), mid))
                        continue
                    try:
                        pasta = pastas.pasta_do_dia(cfg, quando, avisar=registrar)
                    except OSError as e:
                        registrar("ERRO: pasta de destino inacessivel ({}).".format(e))
                        return salvos
                    try:
                        destino = baixar_anexo(ctx, pg, mid, i, pasta)
                    except Exception as e:
                        registrar("ERRO ao baixar '{}': {}".format(nome, str(e)[:110]))
                        continue
                    if not destino:
                        continue
                    ja.add(marca)
                    reg["baixados"].append(marca)
                    gravar_registro(reg)
                    salvos += 1
                    registrar("ARQUIVO SALVO  >>  CLIENTE: {}".format(cfg.get("nome_cliente") or cfg["conversa"]))
                    registrar("    Arquivo: {} ({:.2f} MB)".format(
                        os.path.basename(destino), os.path.getsize(destino) / 1048576))
                    registrar("    Pasta: {}".format(os.path.dirname(destino)))
                    if cfg.get("reagir_ao_baixar", True):
                        registrar("    Visto na mensagem: {}".format(
                            "ok" if reagir(pg, mid) else "falhou"))
            if velhas:
                registrar("({} mensagem(ns) com mais de {} dia(s) ignoradas.)".format(
                    velhas, dias))
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    return salvos


def semear_registro(cfg):
    """Marca tudo que ja esta na tela como visto, sem baixar.

    E o 'corte' dos outros vigias: evita que a primeira execucao baixe de novo
    tudo que ja foi tratado pelo caminho antigo.
    """
    reg = ler_registro()
    ja = set(reg["baixados"])
    novos = 0
    with sync_playwright() as p:
        ctx = abrir(p, visivel=False)
        try:
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(TEAMS, timeout=120000)
            pg.wait_for_timeout(18000)
            if not esta_logado(pg) or not abrir_conversa(pg, cfg["conversa"]):
                return 0
            for item in anexos_recebidos(pg):
                for nome in item["nomes"]:
                    marca = "{}|{}".format(item["mid"], nome)
                    if marca not in ja:
                        ja.add(marca)
                        reg["baixados"].append(marca)
                        novos += 1
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    gravar_registro(reg)
    registrar("Corte aplicado: {} anexo(s) marcados como ja tratados.".format(novos))
    return novos


if __name__ == "__main__":
    main()

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

import marcar_no_grupo
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


def esperar_carregar(pg, segundos_max=40):
    """Espera o Teams ficar pronto, em vez de dormir um tempo fixo.

    Dormir 18 segundos custava isso em TODA passada, mesmo quando o app abria
    em 4. Aqui se olha a tela: assim que ela e o Teams logado, segue.
    """
    limite = time.time() + segundos_max
    while time.time() < limite:
        # A casca do app aparece ANTES da barra lateral. Seguir so por ela
        # fazia o robo dizer que nao achou a conversa, porque a lista ainda
        # nem existia. So esta pronto quando ha conversa para clicar.
        if esta_logado(pg):
            try:
                if pg.locator(SEL_CONVERSA).count():
                    return True
            except Exception:
                pass
        pg.wait_for_timeout(1000)
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
    """Fica rodando, mantendo UMA janela de navegador aberta.

    Reabrir o navegador a cada checagem custava mais tempo do que a checagem em
    si. Aqui a janela e aberta uma vez; se ela morrer, a proxima volta do laco
    abre outra.
    """
    intervalo = int(cfg.get("segundos_entre_checagens", 60))
    registrar("Vigiando a conversa '{}' no Teams Web (a cada {}s). Feche a janela para parar.".format(
        cfg["conversa"], intervalo))
    with sync_playwright() as p:
        ctx = pg = None
        try:
            while True:
                try:
                    if ctx is None:
                        ctx = abrir(p, visivel=bool(cfg.get("mostrar_navegador", False)))
                        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
                    # Recarrega a cada passada, mas NAO reabre o navegador: o
                    # caro e abrir o Chrome, nao carregar a pagina. Reaproveitar
                    # a mesma pagina por horas fez o clique no anexo parar de
                    # abrir a aba do OneDrive - o arquivo era visto e nao baixava.
                    pg.goto(TEAMS, timeout=120000)
                    passada_na_pagina(cfg, ctx, pg)
                except KeyboardInterrupt:
                    registrar("Encerrado pelo usuario.")
                    return
                except Exception as e:
                    registrar("ERRO inesperado: {}".format(str(e)[:150]))
                    # a janela pode ter morrido junto: joga fora e abre outra
                    try:
                        if ctx:
                            ctx.close()
                    except Exception:
                        pass
                    ctx = pg = None
                try:
                    time.sleep(intervalo)
                except KeyboardInterrupt:
                    registrar("Encerrado pelo usuario.")
                    return
                try:
                    cfg = ler_config()
                except (SystemExit, ValueError, OSError):
                    pass
        finally:
            try:
                if ctx:
                    ctx.close()
            except Exception:
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
SEL_TITULO = '[data-tid="chat-title"]'
# A barra de envio troca de prefixo conforme o estado da caixa: com anexo
# pendurado ela vira "newMessageCommands-", sem anexo e "sendMessageCommands-".
# Casar pelo fim do nome pega os dois casos.
SEL_ANEXAR = '[data-tid$="Commands-FilePicker"]'
SEL_CAIXA_TEXTO = '[data-tid="ckeditor"]'
SEL_ENVIAR = '[data-tid$="Commands-send"]'
SEL_TIRAR_ANEXO = '[data-tid="file-chiclet-close"]'

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
            pg.mouse.wheel(0, 6000)
            pg.wait_for_timeout(600)
            agora = pg.evaluate(JS_ULTIMA)
            if agora and agora == ultima:
                parado += 1
                if parado >= 2:      # duas rodadas sem mudar: chegou no fim
                    break
            else:
                parado = 0
                ultima = agora
        pg.mouse.move(5, 5)          # tira a barra de hover da frente
        pg.wait_for_timeout(700)
        if ultima:
            registrar("    fim da conversa: mensagem mais nova e de {}.".format(
                dt.datetime.fromtimestamp(int(ultima) / 1000).strftime("%d/%m/%Y %H:%M")))
    except Exception as e:
        registrar("AVISO: nao consegui ir para o fim da conversa ({}).".format(str(e)[:70]))


def titulo_da_conversa(pg):
    """Nome da conversa aberta, lido do cabecalho. '' se nao der para ler.

    Conferir por quem assina as mensagens nao basta: o NOSSO nome assina em
    todas as conversas, entao um alvo chamado "FINART CTP" daria certo em
    qualquer tela. O titulo e de quem a conversa e.
    """
    try:
        cab = pg.locator(SEL_TITULO).first
        if not cab.count():
            return ""
        return (cab.inner_text(timeout=5000) or "").strip()
    except Exception:
        return ""


def abrir_conversa(pg, nome):
    """Abre a conversa pelo nome e CONFERE que entrou na certa. True se conseguiu.

    Esperar um tempo fixo depois do clique nao serve: o Teams reabre sozinho na
    ultima conversa que esteve aberta, e o clique nem sempre pega de primeira.
    Sem conferir, o robo trabalha na conversa de outro contato - ja aconteceu.
    """
    alvos = pg.locator(SEL_CONVERSA, has_text=nome)
    if not alvos.count():
        registrar("ERRO: nao achei a conversa '{}' na lista.".format(nome))
        return False

    procurado = _sem_acento(nome)
    titulo = ""
    # Mais de uma conversa pode casar com o nome, porque o texto da previa da
    # ultima mensagem tambem conta. Em vez de apostar na primeira, tenta cada
    # uma e para quando o titulo da conversa aberta for o certo.
    for n in range(min(alvos.count(), 5)):
        try:
            alvos.nth(n).click(timeout=20000)
        except Exception as e:
            registrar("AVISO: nao consegui clicar na conversa ({}).".format(str(e)[:70]))
            continue
        limite = time.time() + 20
        while time.time() < limite:
            pg.wait_for_timeout(700)
            titulo = titulo_da_conversa(pg)
            if titulo and procurado in _sem_acento(titulo):
                ir_para_o_fim(pg)
                # rolar carrega outra parte da conversa: confere de novo, porque
                # nao adianta entrar certo e terminar em outro lugar
                fim = titulo_da_conversa(pg)
                if procurado in _sem_acento(fim):
                    return True
                registrar("ERRO: a conversa mudou de '{}' para '{}' ao rolar.".format(
                    titulo, fim))
                return False

    registrar("ERRO: pedi a conversa '{}' e a aberta e '{}'.".format(
        nome, titulo or "(sem titulo legivel)"))
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
        # Rolar ate o anexo antes de clicar: a lista de mensagens e virtualizada
        # e o clique num item que acabou de entrar na tela nao abre a aba do
        # OneDrive - fica esperando um evento que nunca vem.
        chiclet.scroll_into_view_if_needed(timeout=20000)
        pg.wait_for_timeout(1500)
        with ctx.expect_page(timeout=90000) as nova:
            chiclet.click(timeout=20000)
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


def saiu_da_caixa(pg, nome):
    """True quando o arquivo virou mensagem na conversa e a caixa esvaziou.

    Duas condicoes porque uma so engana: a caixa vazia pode ser um anexo
    descartado, e um anexo com esse nome pode ser de mensagem antiga.
    """
    try:
        if pg.locator(SEL_TIRAR_ANEXO).count():
            return False          # ainda pendurado na caixa: nao saiu
        return bool(pg.evaluate("""(nome) => {
            const m = [...document.querySelectorAll('[data-tid="chat-pane-message"]')];
            // olha so o fim da conversa: a mensagem recem-enviada e a ultima.
            // Exige data-mid porque o Teams desenha a mensagem ANTES de o
            // servidor aceitar; enquanto esta so desenhada ela nao tem id, e
            // some se o envio falhar.
            return m.slice(-3).some(e =>
                (e.className || '').toString().includes('ChatMyMessage') &&
                /^[0-9]+$/.test(e.getAttribute('data-mid') || '') &&
                !!e.querySelector('[data-tid="file-chiclet-' + nome + '"]'));
        }""", nome))
    except Exception:
        return False


def enviar_arquivo(pg, caminho, texto=None):
    """Anexa um arquivo na conversa ABERTA e envia. True se saiu.

    Quem chama e responsavel por ja estar na conversa certa (abrir_conversa
    confere isso) - esta funcao nao tem como saber para quem esta mandando.

    O anexo vai pelo campo de arquivo que o Teams cria ao acionar o anexador;
    entregar o caminho ali evita a janela do Windows, que o robo nao consegue
    operar. Enviar pelo navegador dispensa subir para o OneDrive e liberar
    leitura para o cliente: a sessao logada ja resolve a permissao, igual a
    quando a gente anexa na mao.
    """
    if not os.path.exists(caminho):
        registrar("ERRO: nao existe o arquivo para enviar: {}".format(caminho))
        return False
    nome = os.path.basename(caminho)
    try:
        # Um envio que falhou no meio deixa o anexo pendurado na caixa, e ele
        # iria junto do proximo - mandando para o cliente um arquivo que nao
        # era para ir agora. Limpa antes de comecar.
        sobrou = pg.locator(SEL_TIRAR_ANEXO)
        if sobrou.count():
            registrar("    (tirando {} anexo(s) que sobraram na caixa)".format(sobrou.count()))
            for _ in range(10):
                if not sobrou.count():
                    break
                sobrou.first.click(timeout=10000)
                pg.wait_for_timeout(1200)

        pg.locator(SEL_ANEXAR).first.click(timeout=15000)
        pg.wait_for_timeout(2500)
        campo = pg.locator('input[type="file"]').first
        if not campo.count():
            registrar("ERRO: o anexador abriu mas nao apareceu campo de arquivo.")
            pg.keyboard.press("Escape")
            return False
        campo.set_input_files(caminho, timeout=60000)

        # Espera o anexo terminar de subir: enviar antes disso manda mensagem
        # vazia ou com o arquivo pela metade.
        subiu = False
        for _ in range(60):
            pg.wait_for_timeout(2000)
            if pg.locator('[data-tid^="file-chiclet-"]', has_text=nome).count():
                subiu = True
                break
            if pg.locator('[data-tid="{}"]'.format("file-chiclet-" + nome)).count():
                subiu = True
                break
        if not subiu:
            registrar("AVISO: o anexo '{}' nao apareceu na caixa em 2 minutos.".format(nome))
            return False

        if texto:
            caixa = pg.locator(SEL_CAIXA_TEXTO).first
            if caixa.count():
                caixa.click(timeout=10000)
                caixa.type(texto, delay=12)
                pg.wait_for_timeout(800)

        # Clicar em enviar NAO prova que a mensagem saiu. Ja aconteceu de o
        # clique nao pegar, o anexo ficar preso na caixa e o robo dizer que
        # tinha enviado - com o arquivo ja arquivado em ENVIADOS, fora da fila.
        # Por isso aqui se confere o resultado: a mensagem tem que aparecer na
        # conversa E a caixa tem que ficar vazia.
        for tentativa in (1, 2):
            if tentativa == 1:
                botao = pg.locator(SEL_ENVIAR).first
                if botao.count():
                    try:
                        botao.click(timeout=15000)
                    except Exception as e:
                        registrar("    (o botao de enviar nao aceitou o clique: {})".format(
                            str(e)[:60]))
                else:
                    registrar("    (nao achei o botao de enviar; vou pelo teclado)")
                    continue
            else:
                # Ctrl+Enter e o atalho que o proprio Teams anuncia no botao.
                # Serve de segunda via quando o clique nao pega.
                caixa = pg.locator(SEL_CAIXA_TEXTO).first
                if caixa.count():
                    caixa.click(timeout=10000)
                pg.keyboard.press("Control+Enter")

            for _ in range(15):
                pg.wait_for_timeout(2000)
                if not saiu_da_caixa(pg, nome):
                    continue
                # Confirma que FICA. A mensagem aparece na tela antes de o
                # servidor aceitar; se o envio falhar ela some segundos depois,
                # e foi assim que um .ppf ficou dado como enviado sem ter ido.
                pg.wait_for_timeout(7000)
                if saiu_da_caixa(pg, nome):
                    registrar("    enviado: {}".format(nome))
                    return True
                registrar("    (a mensagem apareceu e sumiu - o envio nao pegou)")
                break

        registrar("ERRO: '{}' nao saiu - a mensagem nao apareceu na conversa.".format(nome))
        registrar("    O arquivo continua na fila; nao foi dado como enviado.")
        return False
    except Exception as e:
        registrar("ERRO ao enviar '{}': {}".format(nome, str(e)[:110]))
        try:
            pg.keyboard.press("Escape")
        except Exception:
            pass
        return False


class SessaoNavegador(object):
    """Uma janela de navegador emprestada para varios trabalhos.

    Existe porque o perfil do Chrome (perfil_teams_web) nao aceita dois donos
    ao mesmo tempo: se o vigia que baixa e o que manda os .ppf abrirem cada um
    o seu, o segundo nao sobe. Entao os dois pedem a janela a esta classe.

    Abrir o Chrome custa dezenas de segundos; carregar a pagina custa poucos.
    Por isso 'recarregar' e barato e 'fechar' e caro - reaproveitar a mesma
    pagina por horas, porem, fez o clique no anexo parar de funcionar, entao o
    certo e recarregar a cada rodada e fechar so no fim.
    """

    def __init__(self, visivel=False):
        self.visivel = visivel
        self._pw = None
        self._ctx = None
        self._pg = None
        self._conversa_aberta = None

    def pagina(self):
        if self._pg is not None:
            return self._pg
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._ctx = abrir(self._pw, visivel=self.visivel)
        except Exception as e:
            # O perfil do Chrome aceita um dono so. Se o robo foi morto sem
            # fechar direito, o Chrome dele continua rodando e tranca o perfil
            # - e a mensagem crua do Playwright nao diz isso.
            self.fechar()
            raise RuntimeError(
                "nao consegui abrir o navegador do robo ({}). Provavelmente o Chrome "
                "dele ficou aberto de uma execucao anterior e esta segurando o perfil: "
                "feche as janelas do Chrome do robo (ou encerre chrome.exe no Gerenciador "
                "de Tarefas) e tente de novo.".format(str(e).splitlines()[0][:90]))
        self._pg = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._pg.goto(TEAMS, timeout=120000)
        if not esperar_carregar(self._pg):
            raise RuntimeError("a sessao do Teams caiu - rode TEAMS-WEB-LOGIN.bat")
        return self._pg

    def contexto(self):
        self.pagina()
        return self._ctx

    def recarregar(self):
        """Volta a pagina ao estado limpo, sem fechar o navegador."""
        pg = self.pagina()
        pg.goto(TEAMS, timeout=120000)
        self._conversa_aberta = None
        return esperar_carregar(pg)

    def abrir_conversa(self, conversa):
        """Abre a conversa uma vez so; repetir o pedido nao clica de novo."""
        if self._conversa_aberta == conversa:
            return True
        if not abrir_conversa(self.pagina(), conversa):
            return False
        self._conversa_aberta = conversa
        return True

    def enviar(self, conversa, caminho, nome, texto):
        """Manda o arquivo na conversa, com o nome ja limpo.

        O arquivo vai para o Teams com o nome que o navegador ler do disco,
        entao renomear so na variavel nao bastaria: manda-se uma copia com o
        nome certo, numa pasta temporaria que some no fim.
        """
        import shutil
        import tempfile
        if not self.abrir_conversa(conversa):
            raise RuntimeError("nao consegui abrir a conversa '{}'".format(conversa))
        temporaria = tempfile.mkdtemp(prefix="envio-")
        try:
            copia = os.path.join(temporaria, nome)
            shutil.copy2(caminho, copia)
            if not enviar_arquivo(self.pagina(), copia, texto or None):
                # nao sei em que estado a caixa ficou; forca reabrir a conversa
                self._conversa_aberta = None
                raise RuntimeError("o envio de '{}' nao se confirmou".format(nome))
        finally:
            shutil.rmtree(temporaria, ignore_errors=True)

    def fechar(self):
        for encerrar in (getattr(self._ctx, "close", None), getattr(self._pw, "stop", None)):
            try:
                if encerrar:
                    encerrar()
            except Exception:
                pass
        self._pw = self._ctx = self._pg = None
        self._conversa_aberta = None


def uma_passada(cfg, modo_teste=False):
    """Uma passada avulsa: abre o navegador, faz o trabalho e fecha."""
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
            return passada_na_pagina(cfg, ctx, pg, modo_teste)
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def passada_na_pagina(cfg, ctx, pg, modo_teste=False):
    """O trabalho em si, numa janela que ja esta aberta.

    Separado de uma_passada para o --vigiar poder reaproveitar a mesma janela:
    abrir o navegador custa dezenas de segundos, e pagar isso a cada checagem
    fazia o robo demorar mais para reagir do que a pessoa demoraria na mao.
    """
    reg = ler_registro()
    ja = set(reg["baixados"])
    salvos = 0
    baixados_agora = []
    if not esperar_carregar(pg):
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
            baixados_agora.append(nome)
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

    if not modo_teste:
        # Roda mesmo sem arquivo novo: a Solida as vezes anuncia a OS no grupo
        # DEPOIS de mandar o arquivo, entao as OS que ficaram pendentes
        # precisam ser tentadas de novo a cada passada.
        try:
            marcar_no_grupo.processar(cfg, baixados_agora, registrar)
        except Exception as e:
            registrar("AVISO: falhou ao marcar no grupo do WhatsApp ({}).".format(str(e)[:120]))
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
            if not esperar_carregar(pg) or not abrir_conversa(pg, cfg["conversa"]):
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

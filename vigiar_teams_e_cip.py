# -*- coding: utf-8 -*-
"""Sobe o vigia do Teams e o do CIP no mesmo terminal.

Os dois atendem a Solida e falam com o mesmo chat externo, entao ficam num
terminal so em vez de ocupar duas abas. Cada linha sai marcada com a origem
([TEAMS] ou [CIP]); o log completo de cada um continua no seu proprio arquivo,
vigia_teams.log e vigia_cip.log.

Fechar a janela derruba os dois.
"""

import os
import subprocess
import sys
import threading

AQUI = os.path.dirname(os.path.abspath(__file__))
VIGIAS = [("TEAMS", "vigia_teams.py"), ("CIP", "vigia_cip.py")]


def repassar(rotulo, processo):
    """Copia a saida do filho para este terminal, marcando de quem veio."""
    for linha in processo.stdout:
        sys.stdout.write("[{}] {}".format(rotulo, linha))
        sys.stdout.flush()


def main():
    # PYTHONUNBUFFERED para a saida aparecer na hora, sem ficar presa no buffer
    ambiente = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    processos = []

    for rotulo, script in VIGIAS:
        p = subprocess.Popen(
            [sys.executable, os.path.join(AQUI, script), "--vigiar"],
            cwd=AQUI, env=ambiente,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        processos.append((rotulo, p))
        threading.Thread(target=repassar, args=(rotulo, p), daemon=True).start()
        print("[{}] iniciado (PID {}).".format(rotulo, p.pid), flush=True)

    try:
        # espera qualquer um dos dois morrer; se um cair, derruba o outro junto
        # para nao ficar meio sistema rodando sem ninguem perceber
        while True:
            caiu = [(r, p) for r, p in processos if p.poll() is not None]
            if caiu:
                rotulo, p = caiu[0]
                print("[{}] ENCERROU (codigo {}). Derrubando o outro.".format(
                    rotulo, p.returncode), flush=True)
                break
            try:
                processos[0][1].wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        print("Encerrado pelo usuario.", flush=True)
    finally:
        for rotulo, p in processos:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Anexar arquivo em mensagem de chat do Teams, pela API do Graph.

O Teams nao anexa arquivo de pasta de rede: o anexo precisa ser um item que ja
viva na nuvem. Entao o caminho e sempre subir para o OneDrive e referenciar o
item criado.

Mora em modulo separado porque o vigia do Teams e o vigia do CIP fazem
exatamente isso, e o detalhe do eTag (o id do anexo e o GUID de dentro dele,
nao o id do item) e facil de errar e dificil de descobrir quando erra: a
mensagem chega, mas sem o anexo.
"""

import base64
import urllib.parse

import requests


# Pasta padrao onde o Teams guarda os arquivos mandados em chat. Usando ela, o
# anexo aparece para quem recebe como qualquer arquivo enviado na mao.
PASTA_ONEDRIVE = "Microsoft Teams Chat Files"

# Upload simples (PUT) so aceita ate 4 MB; acima disso usa sessao de upload.
LIMITE_UPLOAD_SIMPLES = 4 * 1024 * 1024
# Pedaco da sessao de upload: tem que ser multiplo de 320 KiB.
PEDACO = 320 * 1024 * 32  # ~10 MB


def subir(graph, token, origem, nome):
    """Sobe o arquivo para o OneDrive e devolve o item criado.

    'graph' e a funcao de chamada da API do script que chamou, para o log e o
    tratamento de erro seguirem sendo os dele. 'origem' aceita caminho no disco
    ou os proprios bytes.
    """
    if isinstance(origem, (bytes, bytearray)):
        dados = origem
    else:
        with open(origem, "rb") as f:
            dados = f.read()
    destino = urllib.parse.quote("{}/{}".format(PASTA_ONEDRIVE, nome))
    if len(dados) <= LIMITE_UPLOAD_SIMPLES:
        url = "/me/drive/root:/{}:/content?@microsoft.graph.conflictBehavior=rename".format(destino)
        r = graph(token, "PUT", url, data=dados,
                  headers={"Content-Type": "application/octet-stream"})
        return r.json()

    # arquivo grande (PDF de impressao costuma passar de 4 MB): sessao de upload
    sessao = graph(token, "POST", "/me/drive/root:/{}:/createUploadSession".format(destino),
                   json={"item": {"@microsoft.graph.conflictBehavior": "rename"}}).json()
    upload_url = sessao["uploadUrl"]
    total = len(dados)
    inicio = 0
    resposta = None
    while inicio < total:
        fim = min(inicio + PEDACO, total) - 1
        # a uploadUrl ja vem autenticada: NAO mandar o cabecalho Authorization
        resposta = requests.put(upload_url, data=dados[inicio:fim + 1], timeout=300, headers={
            "Content-Length": str(fim - inicio + 1),
            "Content-Range": "bytes {}-{}/{}".format(inicio, fim, total),
        })
        if resposta.status_code >= 400:
            raise requests.HTTPError("upload em partes falhou: HTTP {} {}".format(
                resposta.status_code, resposta.text[:200]))
        inicio = fim + 1
    return resposta.json()


def item_existente(graph, token, nome):
    """Item que ja foi subido antes para a pasta de anexos, ou None."""
    destino = urllib.parse.quote("{}/{}".format(PASTA_ONEDRIVE, nome))
    try:
        return graph(token, "GET", "/me/drive/root:/{}".format(destino)).json()
    except Exception as e:  # 404 = nunca subiu
        if getattr(e, "status", None) == 404:
            return None
        raise


def _drive_e_id(item):
    return (item.get("parentReference") or {}).get("driveId"), item.get("id")


def liberar_para(graph, token, item, emails):
    """Da permissao de leitura no item para os e-mails de quem esta no chat.

    Pelo aplicativo do Teams isso acontece sozinho ao anexar; pela API nao.
    Sem isso o cliente clica no anexo e cai em "Voce precisa de acesso".
    """
    emails = [e for e in (emails or []) if e]
    if not emails:
        return
    drive_id, item_id = _drive_e_id(item)
    graph(token, "POST", "/drives/{}/items/{}/invite".format(drive_id, item_id), json={
        "recipients": [{"email": e} for e in emails],
        "roles": ["read"],
        "requireSignIn": True,
        "sendInvitation": False,
    })


def link_publico(graph, token, item):
    """Cria um link 'qualquer pessoa com o link pode ver' e devolve o endereco."""
    drive_id, item_id = _drive_e_id(item)
    r = graph(token, "POST", "/drives/{}/items/{}/createLink".format(drive_id, item_id),
              json={"type": "view", "scope": "anonymous"})
    return ((r.json().get("link") or {}).get("webUrl")) or ""


def item_pelo_link(graph, token, content_url):
    """Acha o item do SharePoint a partir do endereco que veio no anexo do canal."""
    chave = base64.urlsafe_b64encode(content_url.encode("utf-8")).decode("ascii").rstrip("=")
    return graph(token, "GET", "/shares/u!{}/driveItem".format(chave)).json()


def guid_do_item(item):
    """Id que o Teams exige no anexo: o GUID de dentro do eTag do item."""
    etag = item.get("eTag") or ""
    if "{" in etag and "}" in etag:
        return etag.split("{", 1)[1].split("}", 1)[0]
    return item.get("id") or ""


def corpo_com_anexos(itens, texto="", links_html=""):
    """Monta o corpo da mensagem. itens = lista de (nome, item_do_onedrive).

    Cada anexo precisa aparecer duas vezes: como <attachment> no HTML e na
    lista 'attachments'. Faltando qualquer um dos dois o arquivo nao aparece.
    """
    anexos = []
    marcas = []
    for nome, item in itens:
        guid = guid_do_item(item)
        anexos.append({
            "id": guid,
            "contentType": "reference",
            "contentUrl": item.get("webUrl") or "",
            "name": nome,
        })
        marcas.append('<attachment id="{}"></attachment>'.format(guid))
    html = links_html + "".join(marcas)
    if texto:
        html = "<p>{}</p>{}".format(texto, html)
    return {"body": {"contentType": "html", "content": html}, "attachments": anexos}

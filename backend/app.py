from flask import Flask, request, jsonify, send_from_directory
from pathlib import Path
from urllib.parse import urlencode, quote
import requests
import xml.etree.ElementTree as ET
import os
import re

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
MEMORIA_DIR = BASE_DIR / "memoria"
IMAGENS_DIR = BASE_DIR / "backend" / "geradas"
MEMORIA_DIR.mkdir(exist_ok=True)
IMAGENS_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "DaNikeAI-Brain/0.2"

@app.get("/status")
def status():
    return jsonify({
        "nome": "DaNikeAI Brain",
        "status": "online",
        "versao": "0.2.0",
        "recursos": {
            "servidor": True,
            "pesquisa_web": True,
            "noticias": True,
            "geracao_imagens": bool(os.environ.get("POLLINATIONS_API_KEY")),
            "ia_conectada": bool(os.environ.get("HF_TOKEN", "").strip())
        }
    })

@app.post("/notificar")
def notificar():
    dados = request.get_json(silent=True) or {}

    segredo = request.headers.get("X-DaNikeAI-Secret", "")
    segredo_correto = os.environ.get("DANIKEAI_NOTIFY_SECRET", "").strip()

    if not segredo_correto or segredo != segredo_correto:
        return jsonify({"erro": "Não autorizado."}), 401

    uid = str(dados.get("uid", "")).strip()
    tipo = str(dados.get("tipo", "geral")).strip()
    titulo = str(dados.get("titulo", "DaNikeAI")).strip()
    texto = str(dados.get("texto", "")).strip()
    remetente_uid = str(dados.get("remetente_uid", "")).strip()

    if not uid or not texto:
        return jsonify({"erro": "uid e texto são obrigatórios."}), 400

    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()

    if not token:
        return jsonify({"erro": "GITHUB_DISPATCH_TOKEN não configurado."}), 503

    payload = {
        "event_type": "enviar-fcm",
        "client_payload": {
            "uid": uid,
            "tipo": tipo,
            "titulo": titulo,
            "texto": texto,
            "remetente_uid": remetente_uid
        }
    }

    try:
        resposta = SESSION.post(
            "https://api.github.com/repos/andersonptg/DaNikeAI-Brain/dispatches",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=15
        )

        if resposta.status_code != 204:
            print("[NOTIFICACAO GITHUB]", resposta.status_code, resposta.text[:500])
            return jsonify({
                "erro": "Não foi possível disparar a notificação.",
                "status_github": resposta.status_code
            }), 502

        return jsonify({
            "status": "disparado",
            "mensagem": "Notificação enviada para processamento."
        })

    except requests.RequestException as erro:
        print("[NOTIFICACAO]", str(erro)[:300])
        return jsonify({
            "erro": "Falha ao conectar ao GitHub."
        }), 502
@app.post("/chat")
def chat():
    dados = request.get_json(silent=True) or {}
    mensagem = dados.get("mensagem", "")

    if not isinstance(mensagem, str) or not mensagem.strip():
        return jsonify({"erro": "Envie uma mensagem válida."}), 400

    mensagem = mensagem.strip()
    if len(mensagem) > 4000:
        return jsonify({"erro": "Máximo de 4000 caracteres."}), 413

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        return jsonify({
            "erro": "HF_TOKEN não está configurado no servidor.",
            "ia_conectada": False
        }), 503

    try:
        resposta = SESSION.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json"
            },
            json={
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [
                    {
                        "role": "system",
                        "content": "Você é a DaNikeAI, uma assistente útil. Responda em português do Brasil, com clareza e naturalidade."
                    },
                    {"role": "user", "content": mensagem}
                ],
                "max_tokens": 500,
                "temperature": 0.7
            },
            timeout=90
        )

        if not resposta.ok:
            print("[CHAT HF] HTTP", resposta.status_code, resposta.text[:1000])
            return jsonify({
                "erro": "O provedor de IA recusou a solicitação.",
                "status_provedor": resposta.status_code,
                "ia_conectada": False
            }), 502

        dados_ia = resposta.json()
        escolhas = dados_ia.get("choices", [])
        texto = ""
        if escolhas:
            texto = escolhas[0].get("message", {}).get("content", "")

        if not isinstance(texto, str) or not texto.strip():
            return jsonify({
                "erro": "O modelo não retornou uma resposta válida.",
                "ia_conectada": False
            }), 502

        return jsonify({
            "nome": "DaNikeAI",
            "mensagem_recebida": mensagem,
            "resposta": texto.strip(),
            "ia_conectada": True,
            "modelo": dados_ia.get("model", "Qwen/Qwen2.5-7B-Instruct")
        })

    except requests.RequestException:
        return jsonify({
            "erro": "Não foi possível conectar ao provedor de IA.",
            "ia_conectada": False
        }), 502
    except (ValueError, KeyError, TypeError):
        return jsonify({
            "erro": "A resposta do provedor veio em formato inesperado.",
            "ia_conectada": False
        }), 502


@app.get("/pesquisa")
def pesquisa():
    consulta = request.args.get("q", "").strip()
    if not consulta:
        return jsonify({
            "erro": "Informe o que deseja pesquisar.",
            "exemplo": "/pesquisa?q=inteligencia+artificial"
        }), 400

    if len(consulta) > 200:
        return jsonify({"erro": "Consulta muito longa."}), 400

    params = {
        "q": consulta,
        "hl": "pt-BR",
        "gl": "BR",
        "ceid": "BR:pt-419"
    }
    url = "https://news.google.com/rss/search?" + urlencode(params)

    try:
        resposta = SESSION.get(url, timeout=20)
        resposta.raise_for_status()
        raiz = ET.fromstring(resposta.content)
        resultados = []

        for item in raiz.findall("./channel/item")[:3]:
            titulo = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            data = item.findtext("pubDate", "").strip()
            fonte = item.find("source")
            nome_fonte = fonte.text.strip() if fonte is not None and fonte.text else ""

            if titulo and link:
                resultados.append({
                    "titulo": titulo,
                    "fonte": nome_fonte or "Fonte indicada no título",
                    "data": data,
                    "link": link
                })

        return jsonify({
            "consulta": consulta,
            "quantidade": len(resultados),
            "resultados": resultados,
            "aviso": "Confira a matéria original e a data antes de compartilhar."
        })
    except (requests.RequestException, ET.ParseError) as erro:
        return jsonify({
            "erro": "Não foi possível obter as notícias agora.",
            "detalhe": str(erro)[:200]
        }), 502

@app.post("/imagem")
def gerar_imagem():
    dados = request.get_json(silent=True) or {}
    prompt = dados.get("prompt", "")

    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({"erro": "Informe uma descrição para a imagem."}), 400

    prompt = prompt.strip()
    if len(prompt) > 1000:
        return jsonify({"erro": "Descrição limitada a 1000 caracteres."}), 400

    chave = os.environ.get("POLLINATIONS_API_KEY", "").strip()
    if not chave:
        return jsonify({
            "erro": "Geração ainda não configurada.",
            "proximo_passo": (
                "Configure POLLINATIONS_API_KEY no ambiente do Termux. "
                "Verifique o saldo e o custo antes de gerar."
            )
        }), 503

    endpoint = "https://gen.pollinations.ai/image/" + quote(prompt, safe="")
    try:
        resposta = SESSION.get(
            endpoint,
            params={
                "model": "tongyi-mai/z-image-turbo",
                "width": 1024,
                "height": 1024
            },
            headers={"Authorization": "Bearer " + chave},
            timeout=180
        )

        if not resposta.ok:
            return jsonify({
                "erro": "O serviço de imagens recusou a solicitação.",
                "status_servico": resposta.status_code,
                "orientacao": "Confira a chave, o saldo e os limites da conta."
            }), 502

        tipo = resposta.headers.get("Content-Type", "").lower()
        if not tipo.startswith("image/"):
            return jsonify({"erro": "O serviço não retornou um arquivo de imagem."}), 502

        extensao = ".png" if "png" in tipo else ".jpg"
        nome = "danike_" + os.urandom(8).hex() + extensao
        caminho = IMAGENS_DIR / nome
        caminho.write_bytes(resposta.content)

        return jsonify({
            "status": "imagem_criada",
            "arquivo": nome,
            "url": "/imagem/" + nome,
            "modelo": "tongyi-mai/z-image-turbo"
        })
    except requests.RequestException:
        return jsonify({"erro": "Falha de conexão com o gerador de imagens."}), 502

@app.get("/imagem/<path:nome>")
def servir_imagem(nome):
    if not re.fullmatch(r"danike_[a-f0-9]{16}\.(png|jpg)", nome):
        return jsonify({"erro": "Nome de arquivo inválido."}), 400
    return send_from_directory(IMAGENS_DIR, nome)

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", "8769"))
    print(f"DaNikeAI Brain v0.2.0 — porta {porta}")
    app.run(host="0.0.0.0", port=porta, debug=False)

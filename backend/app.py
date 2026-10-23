from flask import Flask, request, jsonify, send_from_directory
from pathlib import Path
from urllib.parse import urlencode, quote
import requests
import xml.etree.ElementTree as ET
import os
import re
import json
import firebase_admin
from firebase_admin import credentials, firestore, messaging

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
MEMORIA_DIR = BASE_DIR / "memoria"
IMAGENS_DIR = BASE_DIR / "backend" / "geradas"
MEMORIA_DIR.mkdir(exist_ok=True)
IMAGENS_DIR.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()

SESSION.headers["User-Agent"] = "DaNikeAI-Brain/0.2"

# Firebase Admin para envio FCM direto pelo Render
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()

if FIREBASE_SERVICE_ACCOUNT_JSON and not firebase_admin._apps:
    try:
        credenciais = credentials.Certificate(json.loads(FIREBASE_SERVICE_ACCOUNT_JSON))
        firebase_admin.initialize_app(credenciais, {"projectId": "da-nike-films"})
        print("[FCM DIRETO] Firebase Admin inicializado.")
    except Exception as erro:
        print("[FCM DIRETO] Falha ao inicializar Firebase:", str(erro)[:500])



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
    fila_id = str(dados.get("fila_id", "")).strip()

    if not uid or not texto:
        return jsonify({"erro": "uid e texto são obrigatórios."}), 400

    # ============================================================
    # ENVIO FCM DIRETO — não passa pelo GitHub Actions
    # ============================================================
    if firebase_admin._apps:
        try:
            db = firestore.client()

            dispositivos_ref = (
                db.collection("usuarios")
                .document(uid)
                .collection("dispositivos")
            )

            tokens = []
            for dispositivo in dispositivos_ref.stream():
                token = (dispositivo.to_dict() or {}).get("token")
                if token:
                    tokens.append(token)

            if not tokens:
                return jsonify({
                    "status": "sem_dispositivo",
                    "mensagem": "Nenhum dispositivo FCM encontrado."
                }), 200

            enviados = 0

            for token in tokens:
                try:
                    mensagem = messaging.Message(
                        data={
                            "tipo": tipo,
                            "titulo": titulo,
                            "texto": texto,
                            "remetenteUid": remetente_uid,
                        },
                        token=token,
                        android=messaging.AndroidConfig(priority="high"),
                    )

                    resposta = messaging.send(mensagem)
                    enviados += 1
                    print("[FCM DIRETO] enviado:", resposta)

                except Exception as erro:
                    print("[FCM DIRETO] erro no token:", str(erro)[:500])

            if enviados > 0:
                if fila_id:
                    try:
                        db.collection("fila_notificacoes").document(fila_id).update({
                            "enviada": True,
                            "emProcessamento": False,
                            "enviadaEm": firestore.SERVER_TIMESTAMP,
                            "totalDispositivos": enviados,
                        })
                    except Exception as erro:
                        print("[FCM DIRETO] erro ao atualizar fila:", str(erro)[:300])

                return jsonify({
                    "status": "enviado",
                    "metodo": "fcm_direto",
                    "totalDispositivos": enviados
                }), 200

            return jsonify({
                "erro": "Nenhum FCM foi enviado."
            }), 502

        except Exception as erro:
            print("[FCM DIRETO] erro geral:", str(erro)[:500])
            return jsonify({
                "erro": "Falha no envio FCM direto."
            }), 502

    # ============================================================
    # FALLBACK — mantém o mecanismo antigo enquanto necessário
    # ============================================================
    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()

    if not token:
        return jsonify({
            "erro": "Firebase direto não configurado e GITHUB_DISPATCH_TOKEN ausente."
        }), 503

    payload = {
        "event_type": "enviar-fcm",
        "client_payload": {
            "uid": uid,
            "tipo": tipo,
            "titulo": titulo,
            "texto": texto,
            "remetente_uid": remetente_uid,
            "fila_id": fila_id
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
            "metodo": "github_fallback"
        }), 200

    except requests.RequestException as erro:
        print("[NOTIFICACAO]", str(erro)[:300])
        return jsonify({
            "erro": "Falha ao conectar ao GitHub."
        }), 502



@app.post("/nexo/publicar-filme")
def nexo_publicar_filme():
    """
    Ponte segura:
    Android -> Render -> Base44.
    O segredo NEXO_ADM_KEY fica somente no Render.
    """

    # ------------------------------------------------------------
    # 1. Autenticacao Firebase
    # ------------------------------------------------------------
    auth = request.headers.get("Authorization", "").strip()

    if not auth.startswith("Bearer "):
        return jsonify({
            "sucesso": False,
            "erro": "Token Firebase ausente."
        }), 401

    firebase_token = auth[7:].strip()

    if not firebase_token:
        return jsonify({
            "sucesso": False,
            "erro": "Token Firebase vazio."
        }), 401

    # Importacao local para nao alterar o restante do servidor.
    try:
        from firebase_admin import auth as firebase_auth

        usuario = firebase_auth.verify_id_token(firebase_token)

        email = str(usuario.get("email", "")).strip().lower()

        if email != "lipesanderson@gmail.com":
            return jsonify({
                "sucesso": False,
                "erro": "Apenas o administrador pode publicar filmes."
            }), 403

    except Exception as erro:
        print("[NEXO] Falha na autenticacao Firebase:", str(erro)[:500])
        return jsonify({
            "sucesso": False,
            "erro": "Token Firebase invalido."
        }), 401

    # ------------------------------------------------------------
    # 2. Dados enviados pelo Android
    # ------------------------------------------------------------
    dados = request.get_json(silent=True) or {}

    titulo = str(dados.get("titulo", "")).strip()

    if not titulo:
        return jsonify({
            "sucesso": False,
            "erro": "titulo e obrigatorio."
        }), 400

    # ------------------------------------------------------------
    # 3. Chave secreta do Base44
    # ------------------------------------------------------------
    chave_base44 = os.environ.get("NEXO_ADM_KEY", "").strip()

    if not chave_base44:
        print("[NEXO] NEXO_ADM_KEY nao configurada no Render.")
        return jsonify({
            "sucesso": False,
            "erro": "NEXO_ADM_KEY nao configurada no servidor."
        }), 503

    # ------------------------------------------------------------
    # 4. Monta payload para a Function do Base44
    # ------------------------------------------------------------
    payload = {
        "titulo": titulo,
        "descricao": str(dados.get("descricao", "")).strip(),
        "ano": dados.get("ano"),
        "categoria": str(dados.get("categoria", "")).strip(),
        "tipo": str(dados.get("tipo", "Filme")).strip() or "Filme",
        "poster_url": str(dados.get("poster_url", "")).strip(),
        "banner_url": str(dados.get("banner_url", "")).strip(),
        "video_url": str(dados.get("video_url", "")).strip(),
        "ativo": bool(dados.get("ativo", True)),
        "destaque": bool(dados.get("destaque", False)),
    }

    url_base44 = (
        "https://nippy-nexo-stream-hub.base44.app"
        "/functions/publicar-filme"
    )

    try:
        resposta = SESSION.post(
            url_base44,
            headers={
                "Authorization": "Bearer " + chave_base44,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=30,
        )

        print(
            "[NEXO] Base44 respondeu:",
            resposta.status_code,
            resposta.text[:1000]
        )

        try:
            retorno = resposta.json()
        except Exception:
            retorno = {
                "resposta": resposta.text[:2000]
            }

        return jsonify({
            "sucesso": resposta.ok,
            "status_base44": resposta.status_code,
            "base44": retorno,
        }), resposta.status_code

    except requests.RequestException as erro:
        print("[NEXO] Erro ao conectar ao Base44:", str(erro)[:1000])

        return jsonify({
            "sucesso": False,
            "erro": "Falha ao conectar ao Base44."
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

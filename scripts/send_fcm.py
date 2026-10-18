import os
import firebase_admin
from firebase_admin import credentials, firestore, messaging

PROJECT_ID = "da-nike-films"

uid = os.environ["NOTIFICACAO_UID"]
tipo = os.environ["NOTIFICACAO_TIPO"]
titulo = os.environ["NOTIFICACAO_TITULO"]
texto = os.environ["NOTIFICACAO_TEXTO"]
remetente_uid = os.environ.get("NOTIFICACAO_REMETENTE_UID", "").strip()

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": PROJECT_ID})

db = firestore.client()

ref = (
    db.collection("usuarios")
      .document(uid)
      .collection("dispositivos")
)

docs = ref.stream()

tokens = []
for doc in docs:
    dados = doc.to_dict() or {}
    token = dados.get("token")
    if token:
        tokens.append(token)

if not tokens:
    raise SystemExit("Nenhum dispositivo FCM encontrado para esse usuário.")

for token in tokens:
    mensagem = messaging.Message(
        data={
            "tipo": tipo,
            "titulo": titulo,
            "texto": texto,
            "remetenteUid": remetente_uid,
        },
        token=token,
        android=messaging.AndroidConfig(
            priority="high"
        ),
    )

    resposta = messaging.send(mensagem)
    print(f"FCM enviado com sucesso: {resposta}")

print(f"Total de dispositivos: {len(tokens)}")

# Evita que o processamento agendado envie novamente
fila = db.collection("fila_notificacoes").where("uid", "==", uid).where("enviada", "==", False).stream()

for doc in fila:
    dados = doc.to_dict() or {}
    if (
        str(dados.get("tipo", "")).strip() == tipo
        and str(dados.get("titulo", "")).strip() == titulo
        and str(dados.get("texto", "")).strip() == texto
        and str(dados.get("remetenteUid", dados.get("remetente_uid", ""))).strip() == remetente_uid
    ):
        doc.reference.update({
            "enviada": True,
            "enviadaEm": firestore.SERVER_TIMESTAMP,
            "totalDispositivos": len(tokens)
        })
        print(f"Fila marcada como enviada: {doc.id}")
        break

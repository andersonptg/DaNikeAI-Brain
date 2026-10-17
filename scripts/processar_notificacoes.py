import firebase_admin
from firebase_admin import firestore, messaging

PROJECT_ID = "da-nike-films"

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": PROJECT_ID})

db = firestore.client()

fila = db.collection("fila_notificacoes").where("enviada", "==", False).stream()

total = 0

for doc in fila:
    dados = doc.to_dict() or {}

    uid = dados.get("uid")
    tipo = dados.get("tipo", "geral")
    titulo = dados.get("titulo", "DaNikeAI")
    texto = dados.get("texto", "")
    remetente_uid = dados.get("remetenteUid", "")

    if not uid:
        print(f"Ignorando {doc.id}: UID ausente.")
        continue

    tokens_ref = (
        db.collection("usuarios")
        .document(uid)
        .collection("dispositivos")
    )

    tokens = []

    for dispositivo in tokens_ref.stream():
        token = (dispositivo.to_dict() or {}).get("token")
        if token:
            tokens.append(token)

    if not tokens:
        print(f"Nenhum dispositivo para {uid}.")
        continue

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
            print(f"FCM enviado: {resposta}")
            enviados += 1

        except Exception as erro:
            print(f"Erro ao enviar para dispositivo: {erro}")

    if enviados > 0:
        doc.reference.update({
            "enviada": True,
            "enviadaEm": firestore.SERVER_TIMESTAMP,
            "totalDispositivos": enviados,
        })
        total += 1

print(f"Notificações processadas: {total}")

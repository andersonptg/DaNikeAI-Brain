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

    @firestore.transactional
    def reservar(transaction):
        snapshot = doc.reference.get(transaction=transaction)
        atual = snapshot.to_dict() or {}

        if atual.get("enviada", False) or atual.get("emProcessamento", False):
            return False

        transaction.update(doc.reference, {
            "emProcessamento": True,
            "processamentoIniciadoEm": firestore.SERVER_TIMESTAMP
        })
        return True

    transaction = db.transaction()

    try:
        reservado = reservar(transaction)
    except Exception as erro:
        print(f"Erro ao reservar {doc.id}: {erro}")
        continue

    if not reservado:
        print(f"Ignorando {doc.id}: já enviada ou em processamento.")
        continue

    uid = dados.get("uid")
    tipo = dados.get("tipo", "geral")
    titulo = dados.get("titulo", "DaNikeAI")
    texto = dados.get("texto", "")
    remetente_uid = dados.get("remetenteUid", "")

    if not uid:
        doc.reference.update({"emProcessamento": False})
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
        doc.reference.update({"emProcessamento": False})
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
            "emProcessamento": False,
            "enviadaEm": firestore.SERVER_TIMESTAMP,
            "totalDispositivos": enviados,
        })
        total += 1
    else:
        doc.reference.update({
            "emProcessamento": False
        })

print(f"Notificações processadas: {total}")

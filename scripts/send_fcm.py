import os

import firebase_admin
from firebase_admin import credentials, firestore, messaging
from firebase_admin._messaging_utils import UnregisteredError

PROJECT_ID = "da-nike-films"

uid = os.environ["NOTIFICACAO_UID"].strip()
tipo = os.environ["NOTIFICACAO_TIPO"].strip()
titulo = os.environ["NOTIFICACAO_TITULO"].strip()
texto = os.environ["NOTIFICACAO_TEXTO"].strip()
remetente_uid = os.environ.get("NOTIFICACAO_REMETENTE_UID", "").strip()
fila_id = os.environ.get("NOTIFICACAO_FILA_ID", "").strip()

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": PROJECT_ID})

db = firestore.client()
fila_ref = (
    db.collection("fila_notificacoes").document(fila_id)
    if fila_id else None
)
reservado = False
finalizado = False


def liberar_reserva():
    if fila_ref is not None and reservado and not finalizado:
        try:
            fila_ref.update({"emProcessamento": False})
            print(f"Reserva liberada para nova tentativa: {fila_id}")
        except Exception as erro:
            print(f"Não foi possível liberar a reserva: {erro}")


try:
    # O envio imediato e o processador automático usam a mesma reserva.
    if fila_ref is not None:
        @firestore.transactional
        def reservar(transaction):
            snapshot = fila_ref.get(transaction=transaction)

            if not snapshot.exists:
                return "nao_encontrada"

            atual = snapshot.to_dict() or {}

            if atual.get("enviada", False):
                return "ja_enviada"

            if atual.get("emProcessamento", False):
                return "em_processamento"

            transaction.update(fila_ref, {
                "emProcessamento": True,
                "processamentoIniciadoEm": firestore.SERVER_TIMESTAMP,
            })
            return "reservada"

        resultado = reservar(db.transaction())

        if resultado != "reservada":
            print(
                f"Envio imediato cancelado para {fila_id}: "
                f"{resultado}. A fila não será enviada por este processo."
            )
            raise SystemExit(0)

        reservado = True

    dispositivos_ref = (
        db.collection("usuarios")
        .document(uid)
        .collection("dispositivos")
    )

    dispositivos = []
    for doc in dispositivos_ref.stream():
        token = (doc.to_dict() or {}).get("token")
        if token:
            dispositivos.append((doc.reference, token))

    enviados = 0
    invalidos = 0

    for doc_ref, token in dispositivos:
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

        try:
            resposta = messaging.send(mensagem)
            enviados += 1
            print(f"FCM enviado com sucesso: {resposta}")

        except UnregisteredError:
            invalidos += 1
            print("Token FCM inválido/desregistrado. Removendo dispositivo...")
            try:
                doc_ref.delete()
                print(f"Dispositivo inválido removido: {doc_ref.id}")
            except Exception as erro:
                print(f"Erro ao remover dispositivo inválido: {erro}")

        except Exception as erro:
            print(f"Erro ao enviar FCM para um dispositivo: {erro}")

    print(f"Total de dispositivos encontrados: {len(dispositivos)}")
    print(f"Total enviados com sucesso: {enviados}")
    print(f"Total de tokens inválidos removidos: {invalidos}")

    if not dispositivos:
        print("Nenhum dispositivo FCM encontrado para esse usuário.")

    if fila_ref is not None:
        if enviados > 0:
            fila_ref.update({
                "enviada": True,
                "emProcessamento": False,
                "enviadaEm": firestore.SERVER_TIMESTAMP,
                "totalDispositivos": enviados,
            })
            print(f"Fila marcada como enviada: {fila_id}")
        else:
            fila_ref.update({"emProcessamento": False})
            print("Nenhum envio concluído; reserva liberada.")

        finalizado = True

    elif enviados == 0:
        raise SystemExit("Nenhuma notificação foi enviada.")

finally:
    liberar_reserva()

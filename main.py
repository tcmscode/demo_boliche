from fastapi import FastAPI, Form, Depends, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from database import engine, Base, get_db
from models import Reserva
from twilio.twiml.messaging_response import MessagingResponse

# Crear las tablas en la base de datos al iniciar
Base.metadata.create_all(bind=engine)

app = FastAPI()

# --- MEMORIA TEMPORAL ---
conversational_state = {}
temp_data = {}

@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...), db: Session = Depends(get_db)):
    """
    Webhook que recibe mensajes de Twilio y responde en XML.
    """
    sender = From
    incoming_msg = Body.strip().lower()
    
    resp = MessagingResponse()
    msg = resp.message()

    # --- MÁQUINA DE ESTADOS ---
    state = conversational_state.get(sender, 'start')

    if state == 'start':
        msg.body("¡Hola! 👋 Bienvenido a *BOLICHE DEMO*.\n\n¿Qué te gustaría hacer hoy?\n1. Comprar Entradas Generales\n2. Reservar Mesa VIP\n\nResponde con el número de la opción.")
        conversational_state[sender] = 'choosing_option'

    elif state == 'choosing_option':
        if incoming_msg == '1':
            temp_data[sender] = {'tipo': 'General'}
            msg.body("Excelente, Entrada General. 🎟️\n¿A nombre de quién las anoto? (Nombre y Apellido)")
            conversational_state[sender] = 'asking_name'
        elif incoming_msg == '2':
            temp_data[sender] = {'tipo': 'Mesa VIP'}
            msg.body("Buena elección, Mesa VIP. 🍾\n¿A nombre de quién hago la reserva?")
            conversational_state[sender] = 'asking_name'
        else:
            msg.body("Por favor, responde '1' o '2'.")

    elif state == 'asking_name':
        if sender not in temp_data: temp_data[sender] = {}
        temp_data[sender]['nombre'] = Body
        msg.body(f"Genial {Body}. ¿Cuántas personas son? (Ingresa solo el número)")
        conversational_state[sender] = 'asking_quantity'

    elif state == 'asking_quantity':
        if incoming_msg.isdigit():
            cantidad = int(incoming_msg)
            data = temp_data.get(sender, {})
            
            # Guardar en DB
            nueva_reserva = Reserva(
                whatsapp_id=sender,
                nombre_completo=data.get('nombre', 'Desconocido'),
                tipo_entrada=data.get('tipo', 'General'),
                cantidad=cantidad,
                confirmada=True
            )
            db.add(nueva_reserva)
            db.commit()
            
            conversational_state[sender] = 'start'
            temp_data[sender] = {}

            msg.body(f"✅ *¡Reserva Confirmada!*\n\nTitular: {nueva_reserva.nombre_completo}\nTipo: {nueva_reserva.tipo_entrada}\nPersonas: {cantidad}\n\nTe esperamos. Mostrá este mensaje en la puerta.")
        else:
            msg.body("Por favor, ingresa solo números.")

    # RESPUESTA XML OBLIGATORIA
    return Response(content=str(resp), media_type="application/xml")

# --- PANEL DE CONTROL VISUAL ---
@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).all()
    
    filas = ""
    for r in reservas:
        filas += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;">{r.id}</td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;">{r.fecha_reserva.strftime('%d/%m %H:%M')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;">{r.whatsapp_id}</td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;"><b>{r.nombre_completo}</b></td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;">
                <span style="background: {'#e3f2fd' if r.tipo_entrada == 'General' else '#fff3e0'}; padding: 5px 10px; border-radius: 15px; font-size: 0.9em;">
                    {r.tipo_entrada}
                </span>
            </td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd; text-align: center;">{r.cantidad}</td>
        </tr>
        """
    
    html = f"""
    <html>
        <head>
            <title>Panel de Reservas</title>
            <meta http-equiv="refresh" content="10"> <style>
                body {{ font-family: 'Segoe UI', sans-serif; margin: 0; padding: 40px; background: #f5f5f5; }}
                .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                h1 {{ color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th {{ text-align: left; padding: 15px 10px; background: #f8f9fa; color: #666; font-weight: 600; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📋 Reservas Confirmadas - Boliche Demo</h1>
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Fecha</th>
                            <th>WhatsApp</th>
                            <th>Cliente</th>
                            <th>Tipo</th>
                            <th>Pax</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filas}
                    </tbody>
                </table>
            </div>
        </body>
    </html>
    """
    return html
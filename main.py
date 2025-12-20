from fastapi import FastAPI, Form, Depends, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import engine, Base, get_db
from models import Reserva
from twilio.twiml.messaging_response import MessagingResponse
import urllib.parse 

# Crear las tablas
Base.metadata.create_all(bind=engine)

app = FastAPI()

# --- MEMORIA TEMPORAL ---
conversational_state = {}
temp_data = {}

@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...), db: Session = Depends(get_db)):
    
    sender = From
    incoming_msg = Body.strip().lower()
    
    resp = MessagingResponse()
    msg = resp.message()

    # --- 🔒 ZONA ADMIN ---
    NUMERO_ADMIN = "whatsapp:+5491131850807" 

    if sender == NUMERO_ADMIN and incoming_msg.startswith("admin"):
        if "stats" in incoming_msg:
            total_reservas = db.query(func.count(Reserva.id)).scalar()
            total_personas = db.query(func.sum(Reserva.cantidad)).scalar() or 0
            msg.body(f"📊 *REPORTE EN VIVO*\n\nTickets/Mesas: {total_reservas}\nPersonas Total: {total_personas}")
            return Response(content=str(resp), media_type="application/xml")
        elif "reset" in incoming_msg:
            db.query(Reserva).delete()
            db.commit()
            msg.body("🗑️ Base de datos borrada.")
            return Response(content=str(resp), media_type="application/xml")
    # --- FIN ADMIN ---

    # --- MÁQUINA DE ESTADOS ---
    state = conversational_state.get(sender, 'start')

    if state == 'start':
        # --- LÓGICA FOMO + FLYER ---
        total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
        cupo_maximo = 150 
        url_flyer = "https://i.ibb.co/mFG17TST/Imagen-Bohemian-Demo.jpg" 

        if total_pax >= cupo_maximo:
             # TEXTO 1: SOLD OUT
             msg.body("⛔ *SOLD OUT* ⛔\n\nCapacidad máxima alcanzada.\n\nGracias por tu interés.")
        
        elif total_pax > (cupo_maximo - 20): 
             # TEXTO 2: ÚLTIMOS LUGARES
             msg.body(f"🔥 *¡Últimos lugares en MOSCU!* 🔥\n\nQuedan {cupo_maximo - total_pax} cupos.\nElegí una opción:\n\n1. 🎫 Entrada General (con QR)\n2. 🍾 Mesa VIP (Lista Exclusiva)")
             msg.media(url_flyer)
             conversational_state[sender] = 'choosing_option'
        else:
             # TEXTO 3: SALUDO NORMAL
             msg.body("¡Hola! Bienvenid@ a *MOSCU*.\n\n¿Qué querés hacer hoy?\n\n1. 🎫 Entrada General (con QR)\n2. 🍾 Mesa VIP (Lista Exclusiva)")
             msg.media(url_flyer) 
             conversational_state[sender] = 'choosing_option'

    elif state == 'choosing_option':
        if incoming_msg == '1':
            # OPCIÓN GENERAL
            temp_data[sender] = {'tipo': 'General', 'nombres_invitados': []}
            # TEXTO 4: PEDIR CANTIDAD
            msg.body("🎫 *Entrada General*\n\n¿Cuántas entradas necesitás?\n\nEnviá solo el número.")
            conversational_state[sender] = 'general_cantidad'
            
        elif incoming_msg == '2':
            # OPCIÓN VIP
            temp_data[sender] = {'tipo': 'Mesa VIP'}
            # TEXTO 10: PEDIR TITULAR VIP
            msg.body("🍾 *Mesa VIP*\n\nBuenísimo. ¿A nombre de quién reservamos la mesa?")
            conversational_state[sender] = 'vip_nombre'
        else:
            msg.body("Por favor, respondé con '1' o '2'.")

    # --- CAMINO GENERAL (Pide nombres 1 por 1) ---
    elif state == 'general_cantidad':
        if incoming_msg.isdigit():
            cantidad = int(incoming_msg)
            if cantidad > 10:
                # TEXTO 5: ERROR MUCHOS
                msg.body("El máximo por compra es 10 entradas.\n\nEnviá una cantidad menor.")
            elif cantidad > 0:
                temp_data[sender]['total_esperado'] = cantidad
                # TEXTO 6: CONFIRMAR Y PEDIR NOMBRE 1
                msg.body(f"Perfecto: {cantidad} personas.\n\nEscribí el *Nombre y Apellido* de la persona nº 1:")
                conversational_state[sender] = 'general_pidiendo_nombres'
            else:
                msg.body("Ingresa un número válido mayor a 0.")
        else:
            msg.body("Por favor ingresa solo números.")

    elif state == 'general_pidiendo_nombres':
        data = temp_data.get(sender)
        nombres = data['nombres_invitados']
        nombres.append(Body.strip().title()) 
        
        total_necesarios = data['total_esperado']
        
        if len(nombres) < total_necesarios:
            # TEXTO 7: PEDIR SIGUIENTE NOMBRE
            msg.body(f"Listo.\n\nAhora escribí el *Nombre y Apellido* de la persona nº {len(nombres) + 1}:")
        else:
            # TEXTO 8: ESPERA GENERACIÓN
            msg.body("⏳ Procesando tus entradas…\n\nTe van a llegar los QRs uno por uno.")
            
            for nombre_invitado in nombres:
                # Guardar en DB
                nueva_reserva = Reserva(
                    whatsapp_id=sender,
                    nombre_completo=nombre_invitado,
                    tipo_entrada="General",
                    cantidad=1,
                    confirmada=True
                )
                db.add(nueva_reserva)
                db.commit()
                
                # Generar QR
                datos_safe = urllib.parse.quote(f"ID:{nueva_reserva.id}|{nombre_invitado}|ACCESO:GENERAL")
                url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={datos_safe}"
                
                # TEXTO 9: ENTREGA TICKET
                mensaje_individual = resp.message(f"✅ Entrada para: *{nombre_invitado}*\nID: {nueva_reserva.id}")
                mensaje_individual.media(url_qr)
            
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            
            return Response(content=str(resp), media_type="application/xml")

    # --- CAMINO VIP (Lista sin QR) ---
    elif state == 'vip_nombre':
        temp_data[sender]['nombre'] = Body
        # TEXTO 11: PEDIR TAMAÑO MESA
        msg.body(f"Bienvenido {Body}.\n\n¿Para cuántas personas es la mesa aprox?\n\n(Solo para organizarnos)")
        conversational_state[sender] = 'vip_cantidad'

    elif state == 'vip_cantidad':
        if incoming_msg.isdigit():
            cantidad = int(incoming_msg)
            data = temp_data.get(sender)
            
            nueva_reserva = Reserva(
                whatsapp_id=sender,
                nombre_completo=data.get('nombre') + " (MESA VIP)",
                tipo_entrada="Mesa VIP",
                cantidad=cantidad,
                confirmada=True
            )
            db.add(nueva_reserva)
            db.commit()
            
            conversational_state[sender] = 'start'
            temp_data[sender] = {}

            # TEXTO 12: CONFIRMACIÓN VIP
            msg.body(f"🥂 *MESA CONFIRMADA*\nTitular: {nueva_reserva.nombre_completo}\nPersonas: {cantidad}\n✅ Ya estás en la Lista Exclusiva.\n\nAl llegar, avisá en puerta VIP tu nombre y te indican el ingreso.")
        else:
            msg.body("Ingresa solo números.")

    return Response(content=str(resp), media_type="application/xml")

# --- PANEL DE CONTROL ---
@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    
    filas = ""
    for r in reservas:
        color = '#e3f2fd' if r.tipo_entrada == 'General' else '#fff3e0'
        estilo_borde = 'border-left: 5px solid gold;' if r.tipo_entrada == 'Mesa VIP' else ''
        
        filas += f"""
        <tr style="{estilo_borde}">
            <td style="padding: 10px; border-bottom: 1px solid #ddd;">{r.id}</td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;">{r.fecha_reserva.strftime('%H:%M')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;"><b>{r.nombre_completo}</b></td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;">
                <span style="background: {color}; padding: 5px 10px; border-radius: 15px; font-size: 0.9em; font-weight:bold;">
                    {r.tipo_entrada}
                </span>
            </td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd; text-align: center;">{r.cantidad}</td>
        </tr>
        """
    
    html = f"""
    <html>
        <head>
            <title>Panel MOSCU</title>
            <meta http-equiv="refresh" content="5"> 
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
                .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                h1 {{ color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th {{ text-align: left; padding: 15px 10px; background: #f8f9fa; color: #666; font-weight: 600; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📋 Access Control - MOSCU</h1>
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Hora</th>
                            <th>Nombre / Titular</th>
                            <th>Acceso</th>
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
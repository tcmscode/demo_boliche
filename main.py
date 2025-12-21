from fastapi import FastAPI, Form, Depends, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import func
from twilio.twiml.messaging_response import MessagingResponse
import urllib.parse 
import datetime
import os

# --- CONFIGURACIÓN DATABASE ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:password@localhost/dbname")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELO DB ---
class Reserva(Base):
    __tablename__ = "reservas_v2"
    
    id = Column(Integer, primary_key=True, index=True)
    whatsapp_id = Column(String, index=True)
    nombre_completo = Column(String)
    tipo_entrada = Column(String) 
    cantidad = Column(Integer)
    confirmada = Column(Boolean, default=False)
    fecha_reserva = Column(DateTime, default=datetime.datetime.utcnow)
    rrpp_asignado = Column(String, default="Organico")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()

# --- DIRECTORIO RRPP ---
DIRECTORIO_RRPP = {
    "matias": {"nombre": "Matias (RRPP)", "celular": "5491111111111"},
    "sofia":  {"nombre": "Sofia (RRPP)", "celular": "5491122222222"},
    "general": {"nombre": "Soporte General", "celular": "5491133333333"}
}

# --- MEMORIA DEL SISTEMA ---
conversational_state = {}
temp_data = {}
user_attribution = {} 

# --- CONFIGURACIÓN ADMIN ---
ADMIN_PASSWORD = "Moscu123"
CUPO_TOTAL = 150

@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...), db: Session = Depends(get_db)):
    
    sender = From
    incoming_msg = Body.strip() # Respetamos mayúsculas/minúsculas para passwords, pero limpiamos espacios
    msg_lower = incoming_msg.lower()
    
    resp = MessagingResponse()
    msg = resp.message()

    # --- 🛡️ SISTEMA OPERATIVO ADMIN (BOLICHE OS) ---
    
    # 1. Trigger de entrada
    if msg_lower == "/admin":
        conversational_state[sender] = 'admin_auth'
        msg.body("🔐 *SISTEMA SEGURO MOSCU*\n\nPor favor, ingresá la contraseña de administrador:")
        return Response(content=str(resp), media_type="application/xml")
    
    # 2. Lógica de Autenticación y Menú
    state = conversational_state.get(sender, 'start')

    if state == 'admin_auth':
        if incoming_msg == ADMIN_PASSWORD:
            conversational_state[sender] = 'admin_menu'
            msg.body("✅ *Acceso Permitido*\nBienvenido al Boliche OS v1.0\n\n*MENÚ PRINCIPAL:*\n\n1. 📊 Ver Dashboard en Vivo\n2. 📢 Crear Difusión (Broadcast)\n3. 🎫 Alta VIP Manual (Rápida)\n4. 🚪 Salir del Sistema\n\n_Enviá el número de la opción._")
        else:
            conversational_state[sender] = 'start' # Lo patea afuera
            msg.body("❌ Contraseña incorrecta. Acceso denegado.")
        return Response(content=str(resp), media_type="application/xml")

    # 3. Herramientas del Menú Admin
    if state == 'admin_menu':
        if msg_lower == '1':
            # --- DASHBOARD ---
            total_reservas = db.query(func.count(Reserva.id)).scalar()
            total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
            ocupacion = int((total_pax / CUPO_TOTAL) * 100)
            msg.body(f"📊 *DASHBOARD EN VIVO*\n\n👥 Pax Totales: {total_pax}/{CUPO_TOTAL}\n📉 Ocupación: {ocupacion}%\n🎫 Tickets Emitidos: {total_reservas}\n\n_Escribí 0 para volver al menú._")
        
        elif msg_lower == '2':
            # --- BROADCAST SETUP ---
            conversational_state[sender] = 'admin_broadcast_draft'
            msg.body("📢 *MODO DIFUSIÓN*\n\nEscribí el mensaje que querés enviar a TODA la base de datos.\n(Podés incluir emojis y links).\n\n_Escribí CANCELAR para volver._")
        
        elif msg_lower == '3':
            # --- ALTA MANUAL ---
            conversational_state[sender] = 'admin_manual_add'
            msg.body("🎫 *ALTA RÁPIDA VIP*\n\nIngresá los datos así: *Nombre, Cantidad*\nEjemplo: _Ricky Fort, 5_")
        
        elif msg_lower == '4':
            # --- SALIR ---
            conversational_state[sender] = 'start'
            msg.body("🔒 Sesión cerrada. Volviendo a modo bot.")
        
        else:
            msg.body("Opción no válida. Enviá 1, 2, 3 o 4.")
        
        return Response(content=str(resp), media_type="application/xml")

    # 4. Lógica interna de herramientas Admin
    if state == 'admin_broadcast_draft':
        if msg_lower == "cancelar":
            conversational_state[sender] = 'admin_menu'
            msg.body("Difusión cancelada. Volviendo al menú.")
        else:
            # Guardamos el borrador
            temp_data[sender] = {'broadcast_msg': incoming_msg}
            # Calculamos alcance
            usuarios_unicos = db.query(Reserva.whatsapp_id).distinct().count()
            conversational_state[sender] = 'admin_broadcast_confirm'
            msg.body(f"⚠️ *CONFIRMACIÓN DE ENVÍO*\n\nVas a enviar este mensaje a *{usuarios_unicos} usuarios*.\n\n_Mensaje:_\n\"{incoming_msg}\"\n\n¿Estás seguro?\n1. ✅ SI, ENVIAR\n2. ❌ NO, CANCELAR")
        return Response(content=str(resp), media_type="application/xml")

    if state == 'admin_broadcast_confirm':
        if msg_lower == '1':
            # Aquí iría la lógica de Twilio Client API para iterar y enviar real.
            # Para la demo, simulamos el éxito.
            usuarios_unicos = db.query(Reserva.whatsapp_id).distinct().count()
            msg.body(f"🚀 *DIFUSIÓN COMPLETADA*\n\nEl mensaje se envió exitosamente a {usuarios_unicos} destinatarios.\n\n_Volviendo al menú..._")
            conversational_state[sender] = 'admin_menu'
        else:
            msg.body("Operación cancelada. Volviendo al menú.")
            conversational_state[sender] = 'admin_menu'
        return Response(content=str(resp), media_type="application/xml")

    if state == 'admin_manual_add':
        try:
            # Parseamos "Nombre, Cantidad"
            datos = incoming_msg.split(',')
            nombre = datos[0].strip().title()
            cantidad = int(datos[1].strip())
            
            # Guardamos directo
            nueva_reserva = Reserva(
                whatsapp_id=sender, # Queda a nombre del admin o se podría poner "Manual"
                nombre_completo=nombre + " (VIP MANUAL)",
                tipo_entrada="Mesa VIP",
                cantidad=cantidad,
                confirmada=True,
                rrpp_asignado="Dueño/Admin"
            )
            db.add(nueva_reserva)
            db.commit()
            
            # Generamos QR para reenviar
            url_validacion = f"https://bot-boliche-demo.onrender.com/check/{nueva_reserva.id}"
            url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={url_validacion}"
            
            msg.body(f"✅ *Alta Exitosa*\nSe generó la entrada para *{nombre}* ({cantidad} pax).")
            msg.media(url_qr)
            
            # Pequeño hack: enviamos otro mensaje para volver al menú
            # En XML no se puede enviar 2 msg bodies separados fácil sin delay, 
            # así que dejamos al admin ahí o le pedimos que escriba algo.
            # Lo dejamos en loop de manual add por si quiere agregar otro.
            msg.body("¿Querés agregar otro? Enviá 'Nombre, Cantidad' o escribí 'MENU' para salir.")
            
        except:
            if msg_lower == "menu":
                conversational_state[sender] = 'admin_menu'
                msg.body("Volviendo al menú.")
            else:
                msg.body("⚠️ *Error de Formato*\n\nTenés que escribir: Nombre, Cantidad\nEjemplo: _Messi, 10_")
        
        return Response(content=str(resp), media_type="application/xml")

    # --- FIN LÓGICA ADMIN ---


    # --- INICIO LÓGICA USUARIO NORMAL (CLIENTE) ---
    
    # Atribución RRPP
    rrpp_detectado = "Organico"
    if "vengo de" in msg_lower:
        partes = msg_lower.split("vengo de ")
        if len(partes) > 1:
            posible_nombre = partes[1].strip().split(" ")[0]
            if posible_nombre in DIRECTORIO_RRPP:
                user_attribution[sender] = posible_nombre
                rrpp_detectado = posible_nombre
                temp_data[sender] = {'rrpp_origen': posible_nombre}
    
    if sender in user_attribution:
        rrpp_detectado = user_attribution[sender]

    # Trigger Cumpleaños
    if "cumple" in msg_lower:
         msg.body("🎂 *¡Feliz Cumpleaños!* 🎂\n\n🎁 Si traes a 10 amigos, te regalamos un Champagne.\nEscribí '1' para reservar.")
         return Response(content=str(resp), media_type="application/xml")

    # Máquina de Estados Cliente
    state = conversational_state.get(sender, 'start')

    if state == 'start':
        total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
        url_flyer = "https://i.ibb.co/mFG17TST/Imagen-Bohemian-Demo.jpg" 

        saludo_extra = ""
        if sender in temp_data and 'rrpp_origen' in temp_data[sender]:
            nombre = DIRECTORIO_RRPP[temp_data[sender]['rrpp_origen']]['nombre']
            saludo_extra = f"👋 ¡Te envía *{nombre}*!\n"

        if total_pax >= CUPO_TOTAL:
             msg.body("⛔ *SOLD OUT* ⛔\n\nCapacidad máxima alcanzada.")
        elif total_pax > (CUPO_TOTAL - 20): 
             msg.body(f"{saludo_extra}🔥 *¡Últimos lugares en MOSCU!* 🔥\nQuedan {CUPO_TOTAL - total_pax} cupos.\n\n1. 🎫 Entrada General (con QR)\n2. 🍾 Mesa VIP (Lista)\n3. 🙋 Ayuda (RRPP)")
             msg.media(url_flyer)
             conversational_state[sender] = 'choosing_option'
        else:
             msg.body(f"{saludo_extra}¡Hola! Bienvenid@ a *MOSCU*.\n\n¿Qué querés hacer hoy?\n\n1. 🎫 Entrada General (con QR)\n2. 🍾 Mesa VIP (Lista)\n3. 🙋 Ayuda (RRPP)")
             msg.media(url_flyer) 
             conversational_state[sender] = 'choosing_option'

    elif state == 'choosing_option':
        if msg_lower == '1':
            temp_data[sender] = {'tipo': 'General', 'nombres_invitados': [], 'rrpp': rrpp_detectado}
            msg.body("🎫 *Entrada General*\n\n¿Cuántas entradas necesitás? (Enviá número)")
            conversational_state[sender] = 'general_cantidad'
        elif msg_lower == '2':
            temp_data[sender] = {'tipo': 'Mesa VIP', 'rrpp': rrpp_detectado}
            msg.body("🍾 *Mesa VIP*\n\n¿A nombre de quién reservamos?")
            conversational_state[sender] = 'vip_nombre'
        elif msg_lower == '3':
            rrpp_usuario = user_attribution.get(sender, 'general')
            datos = DIRECTORIO_RRPP.get(rrpp_usuario, DIRECTORIO_RRPP['general'])
            link_wa = f"https://wa.me/{datos['celular']}?text=Hola,%20necesito%20ayuda"
            msg.body(f"📞 *Derivación Inteligente*\nHabla con tu RRPP asignado: *{datos['nombre']}*.\n👉 {link_wa}")
            conversational_state[sender] = 'start'
        else:
            msg.body("Respondé 1, 2 o 3.")

    elif state == 'general_cantidad':
        if msg_lower.isdigit():
            cantidad = int(msg_lower)
            if cantidad > 0:
                if sender not in temp_data: temp_data[sender] = {}
                temp_data[sender]['total_esperado'] = cantidad
                msg.body(f"Perfecto: {cantidad} personas.\nEscribí el *Nombre y Apellido* de la nº 1:")
                conversational_state[sender] = 'general_pidiendo_nombres'
            else:
                msg.body("Número inválido.")
        else:
            msg.body("Solo números.")

    elif state == 'general_pidiendo_nombres':
        data = temp_data.get(sender)
        nombres = data['nombres_invitados']
        nombres.append(incoming_msg.title()) 
        
        if len(nombres) < data['total_esperado']:
            msg.body(f"Listo. Nombre de la persona nº {len(nombres) + 1}:")
        else:
            msg.body("⏳ Generando Accesos Digitales Únicos...")
            rrpp_final = data.get('rrpp', 'Organico')

            for nombre_invitado in nombres:
                nueva_reserva = Reserva(
                    whatsapp_id=sender,
                    nombre_completo=nombre_invitado,
                    tipo_entrada="General",
                    cantidad=1,
                    confirmada=True,
                    rrpp_asignado=rrpp_final
                )
                db.add(nueva_reserva)
                db.commit()
                
                url_validacion = f"https://bot-boliche-demo.onrender.com/check/{nueva_reserva.id}"
                url_qr_image = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={url_validacion}"
                
                mensaje = resp.message(f"✅ Ticket Digital: *{nombre_invitado}*\nID: {nueva_reserva.id}")
                mensaje.media(url_qr_image)
            
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            return Response(content=str(resp), media_type="application/xml")

    elif state == 'vip_nombre':
        temp_data[sender]['nombre'] = incoming_msg
        msg.body(f"Bienvenido {incoming_msg}. ¿Cuántas personas aprox?")
        conversational_state[sender] = 'vip_cantidad'

    elif state == 'vip_cantidad':
        if msg_lower.isdigit():
            cantidad = int(msg_lower)
            data = temp_data.get(sender)
            nueva_reserva = Reserva(
                whatsapp_id=sender,
                nombre_completo=data.get('nombre') + " (MESA VIP)",
                tipo_entrada="Mesa VIP",
                cantidad=cantidad,
                confirmada=True,
                rrpp_asignado=data.get('rrpp', 'Organico')
            )
            db.add(nueva_reserva)
            db.commit()
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            msg.body(f"🥂 *MESA CONFIRMADA*\nTitular: {nueva_reserva.nombre_completo}\n\nPresentate en Puerta VIP.")
        else:
            msg.body("Solo números.")

    return Response(content=str(resp), media_type="application/xml")

# --- ENDPOINTS EXTRA (SCANNER & PANEL) ---

@app.get("/check/{ticket_id}", response_class=HTMLResponse)
def validar_ticket(ticket_id: int, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == ticket_id).first()
    if not reserva:
        return """<html><body style="background:#e74c3c;color:white;text-align:center;font-family:sans-serif;padding-top:50px;">
        <h1 style="font-size:80px;">❌</h1><h1>TICKET INVÁLIDO</h1></body></html>"""
    
    return f"""<html><body style="background:#2ecc71;color:white;text-align:center;font-family:sans-serif;padding-top:50px;">
        <h1 style="font-size:80px;">✅</h1><h1>ACCESO PERMITIDO</h1>
        <h2>{reserva.nombre_completo}</h2><p>{reserva.tipo_entrada}</p></body></html>"""

@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    
    # Datos para el Gráfico
    total_general = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'General').scalar() or 0
    total_vip = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'Mesa VIP').scalar() or 0
    
    filas = ""
    for r in reservas:
        color_badge = '#2980b9' if r.tipo_entrada == 'General' else '#d35400'
        rrpp_color = '#27ae60' if r.rrpp_asignado != 'Organico' else '#7f8c8d'
        filas += f"""<tr><td>{r.id}</td><td>{r.fecha_reserva.strftime('%H:%M')}</td><td>{r.whatsapp_id}</td>
            <td style="font-weight:bold;color:#ecf0f1;">{r.nombre_completo}</td>
            <td><span style="background:{color_badge};padding:4px 8px;border-radius:4px;">{r.tipo_entrada}</span></td>
            <td>{r.cantidad}</td><td style="color:{rrpp_color};font-weight:bold;">{r.rrpp_asignado}</td></tr>"""
    
    html = f"""
    <html>
    <head>
        <title>MOSCU Night Manager</title>
        <meta http-equiv="refresh" content="10">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
            function exportTableToCSV(filename) {{
                var csv = [];
                var rows = document.querySelectorAll("table tr");
                for (var i = 0; i < rows.length; i++) {{
                    var row = [], cols = rows[i].querySelectorAll("td, th");
                    for (var j = 0; j < cols.length; j++) {{
                        var data = cols[j].innerText.replace(/(\\r\\n|\\n|\\r)/gm, "").replace(/(\\s\\s)/gm, " ");
                        data = data.replace(/"/g, '""');
                        row.push('"' + data + '"');
                    }}
                    csv.push(row.join(","));        
                }}
                var csvString = "\\uFEFF" + csv.join("\\n");
                var blob = new Blob([csvString], {{ type: 'text/csv; charset=utf-8;' }});
                var link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                link.download = filename;
                link.click();
            }}
        </script>
        <style>
            body {{ background-color: #121212; color: #ecf0f1; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: #1e1e1e; padding: 20px; border-radius: 10px; }}
            h1 {{ color: #e74c3c; border-bottom: 1px solid #333; padding-bottom: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th {{ text-align: left; padding: 15px; background: #2c3e50; color: #bdc3c7; }}
            td {{ padding: 15px; border-bottom: 1px solid #333; }}
            .chart-container {{ width: 400px; margin: 20px auto; }}
            .btn-export {{ background: #27ae60; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; float: right; }}
        </style>
    </head>
    <body>
        <div class="container">
            <button class="btn-export" onclick="exportTableToCSV('reservas_moscu.csv')">💾 EXPORTAR EXCEL</button>
            <h1>🦁 MOSCU Access Control</h1>
            
            <div class="chart-container">
                <canvas id="myChart"></canvas>
            </div>
            
            <table>
                <thead><tr><th>ID</th><th>Hora</th><th>WhatsApp</th><th>Nombre</th><th>Tipo</th><th>Pax</th><th>RRPP</th></tr></thead>
                <tbody>{filas}</tbody>
            </table>
        </div>
        <script>
            const ctx = document.getElementById('myChart');
            new Chart(ctx, {{
                type: 'doughnut',
                data: {{
                    labels: ['General', 'VIP'],
                    datasets: [{{
                        data: [{total_general}, {total_vip}],
                        backgroundColor: ['#2980b9', '#d35400'],
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    plugins: {{ legend: {{ labels: {{ color: 'white' }} }} }}
                }}
            }});
        </script>
    </body>
    </html>
    """
    return html
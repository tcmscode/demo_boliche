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

# --- MEMORIA ---
conversational_state = {}
temp_data = {}
user_attribution = {} 

@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...), db: Session = Depends(get_db)):
    
    sender = From
    incoming_msg = Body.strip().lower()
    
    resp = MessagingResponse()
    msg = resp.message()

    # --- 🔒 ADMIN ---
    NUMERO_ADMIN = "whatsapp:+5491131850807" 

    if sender == NUMERO_ADMIN and incoming_msg.startswith("admin"):
        if "stats" in incoming_msg:
            total_reservas = db.query(func.count(Reserva.id)).scalar()
            total_personas = db.query(func.sum(Reserva.cantidad)).scalar() or 0
            msg.body(f"📊 *MOSCU DASHBOARD*\n\nTickets: {total_reservas}\nPax Total: {total_personas}\nStatus: System Operational 🟢")
            return Response(content=str(resp), media_type="application/xml")
        elif "reset" in incoming_msg:
            db.query(Reserva).delete()
            db.commit()
            msg.body("🗑️ Database flushed.")
            return Response(content=str(resp), media_type="application/xml")

    # --- ATRIBUCIÓN RRPP ---
    rrpp_detectado = "Organico"
    if "vengo de" in incoming_msg:
        partes = incoming_msg.split("vengo de ")
        if len(partes) > 1:
            posible_nombre = partes[1].strip().split(" ")[0]
            if posible_nombre in DIRECTORIO_RRPP:
                user_attribution[sender] = posible_nombre
                rrpp_detectado = posible_nombre
                temp_data[sender] = {'rrpp_origen': posible_nombre}
    
    if sender in user_attribution:
        rrpp_detectado = user_attribution[sender]

    # --- TRIGGER DE CUMPLEAÑOS (NUEVO) ---
    if "cumple" in incoming_msg or "cumpleaños" in incoming_msg:
         msg.body("🎂 *¡Feliz Cumpleaños!* 🎂\n\nEn **MOSCU** amamos los festejos.\n\n🎁 *Tu Regalo:* Si traes a 10 amigos, te regalamos un Champagne con Bengalas.\n\nEscribí '1' para sacar tus entradas ahora y asegurar el beneficio.")
         # No cambiamos el estado para que pueda seguir el flujo normal si escribe 1
         return Response(content=str(resp), media_type="application/xml")


    # --- MÁQUINA DE ESTADOS ---
    state = conversational_state.get(sender, 'start')

    if state == 'start':
        total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
        cupo_maximo = 150 
        url_flyer = "https://i.ibb.co/mFG17TST/Imagen-Bohemian-Demo.jpg" 

        saludo_extra = ""
        if sender in temp_data and 'rrpp_origen' in temp_data[sender]:
            nombre_rrpp = DIRECTORIO_RRPP[temp_data[sender]['rrpp_origen']]['nombre']
            saludo_extra = f"👋 ¡Te envía *{nombre_rrpp}*!\n"

        if total_pax >= cupo_maximo:
             msg.body("⛔ *SOLD OUT* ⛔\n\nCapacidad máxima alcanzada.")
        elif total_pax > (cupo_maximo - 20): 
             msg.body(f"{saludo_extra}🔥 *¡Últimos lugares en MOSCU!* 🔥\nQuedan {cupo_maximo - total_pax} cupos.\n\n1. 🎫 Entrada General (con QR)\n2. 🍾 Mesa VIP (Lista)\n3. 🙋 Ayuda (RRPP)")
             msg.media(url_flyer)
             conversational_state[sender] = 'choosing_option'
        else:
             msg.body(f"{saludo_extra}¡Hola! Bienvenid@ a *MOSCU*.\n\n¿Qué querés hacer hoy?\n\n1. 🎫 Entrada General (con QR)\n2. 🍾 Mesa VIP (Lista)\n3. 🙋 Ayuda (RRPP)")
             msg.media(url_flyer) 
             conversational_state[sender] = 'choosing_option'

    elif state == 'choosing_option':
        if incoming_msg == '1':
            temp_data[sender] = {'tipo': 'General', 'nombres_invitados': [], 'rrpp': rrpp_detectado}
            msg.body("🎫 *Entrada General*\n\n¿Cuántas entradas necesitás? (Enviá número)")
            conversational_state[sender] = 'general_cantidad'
        elif incoming_msg == '2':
            temp_data[sender] = {'tipo': 'Mesa VIP', 'rrpp': rrpp_detectado}
            msg.body("🍾 *Mesa VIP*\n\n¿A nombre de quién reservamos?")
            conversational_state[sender] = 'vip_nombre'
        elif incoming_msg == '3':
            rrpp_usuario = user_attribution.get(sender, 'general')
            datos = DIRECTORIO_RRPP.get(rrpp_usuario, DIRECTORIO_RRPP['general'])
            link_wa = f"https://wa.me/{datos['celular']}?text=Hola,%20necesito%20ayuda"
            msg.body(f"📞 *Derivación Inteligente*\nHabla con tu RRPP asignado: *{datos['nombre']}*.\n👉 {link_wa}")
            conversational_state[sender] = 'start'
        else:
            msg.body("Respondé 1, 2 o 3.")

    elif state == 'general_cantidad':
        if incoming_msg.isdigit():
            cantidad = int(incoming_msg)
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
        nombres.append(Body.strip().title()) 
        
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
                
                # --- AQUÍ ESTÁ EL CAMBIO TÉCNICO IMPORTANTE ---
                # El QR ya no es texto, es una URL que apunta a TU servidor para validar
                # Reemplaza 'bot-boliche-demo' con tu nombre real si cambia, pero Render usa variables
                url_validacion = f"https://bot-boliche-demo.onrender.com/check/{nueva_reserva.id}"
                
                url_qr_image = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={url_validacion}"
                
                mensaje = resp.message(f"✅ Ticket Digital: *{nombre_invitado}*\nID: {nueva_reserva.id}")
                mensaje.media(url_qr_image)
            
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            return Response(content=str(resp), media_type="application/xml")

    elif state == 'vip_nombre':
        temp_data[sender]['nombre'] = Body
        msg.body(f"Bienvenido {Body}. ¿Cuántas personas aprox?")
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

# --- NUEVO: ENDPOINT DE VALIDACIÓN (SCANNER) ---
@app.get("/check/{ticket_id}", response_class=HTMLResponse)
def validar_ticket(ticket_id: int, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == ticket_id).first()
    
    if not reserva:
        # PANTALLA ROJA (INVALIDO)
        return """
        <html><body style="background-color: #e74c3c; color: white; font-family: sans-serif; text-align: center; padding-top: 50px;">
            <h1 style="font-size: 80px;">❌</h1>
            <h1>TICKET INVÁLIDO</h1>
            <p>No existe en base de datos.</p>
        </body></html>
        """
    
    # PANTALLA VERDE (VALIDO)
    return f"""
    <html><body style="background-color: #2ecc71; color: white; font-family: sans-serif; text-align: center; padding-top: 50px;">
        <h1 style="font-size: 80px;">✅</h1>
        <h1>ACCESO PERMITIDO</h1>
        <h2>{reserva.nombre_completo}</h2>
        <p>Tipo: {reserva.tipo_entrada}</p>
        <p>RRPP: {reserva.rrpp_asignado}</p>
        <div style="margin-top: 40px; padding: 20px; background: rgba(0,0,0,0.2);">
            <p>ID #{reserva.id} - Verificado en Sistema MOSCU</p>
        </div>
    </body></html>
    """

# --- PANEL OSCURO CON EXCEL ---
@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    
    filas = ""
    for r in reservas:
        color_badge = '#2980b9' if r.tipo_entrada == 'General' else '#d35400'
        rrpp_color = '#27ae60' if r.rrpp_asignado != 'Organico' else '#7f8c8d'
        
        filas += f"""
        <tr>
            <td>#{r.id}</td>
            <td>{r.fecha_reserva.strftime('%H:%M')}</td>
            <td>{r.whatsapp_id}</td>
            <td style="font-weight:bold; color: #ecf0f1;">{r.nombre_completo}</td>
            <td><span style="background:{color_badge}; padding: 4px 8px; border-radius: 4px;">{r.tipo_entrada}</span></td>
            <td>{r.cantidad}</td>
            <td style="color:{rrpp_color}; font-weight:bold;">{r.rrpp_asignado}</td>
        </tr>
        """
    
    html = f"""
    <html>
    <head>
        <title>MOSCU Night Manager</title>
        <meta http-equiv="refresh" content="10">
        <script>
            function exportTableToCSV(filename) {{
                var csv = [];
                var rows = document.querySelectorAll("table tr");
                for (var i = 0; i < rows.length; i++) {{
                    var row = [], cols = rows[i].querySelectorAll("td, th");
                    for (var j = 0; j < cols.length; j++) 
                        row.push(cols[j].innerText);
                    csv.push(row.join(","));        
                }}
                downloadCSV(csv.join("\\n"), filename);
            }}
            function downloadCSV(csv, filename) {{
                var csvFile;
                var downloadLink;
                csvFile = new Blob([csv], {{type: "text/csv"}});
                downloadLink = document.createElement("a");
                downloadLink.download = filename;
                downloadLink.href = window.URL.createObjectURL(csvFile);
                downloadLink.style.display = "none";
                document.body.appendChild(downloadLink);
                downloadLink.click();
            }}
        </script>
        <style>
            body {{ background-color: #121212; color: #ecf0f1; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: #1e1e1e; padding: 20px; border-radius: 10px; box-shadow: 0 0 20px rgba(0,0,0,0.5); }}
            h1 {{ color: #e74c3c; text-transform: uppercase; letter-spacing: 2px; border-bottom: 1px solid #333; padding-bottom: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th {{ text-align: left; padding: 15px; background: #2c3e50; color: #bdc3c7; }}
            td {{ padding: 15px; border-bottom: 1px solid #333; }}
            tr:hover {{ background-color: #2c2c2c; }}
            .btn-export {{ background: #27ae60; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; float: right; font-weight: bold; }}
            .btn-export:hover {{ background: #2ecc71; }}
        </style>
    </head>
    <body>
        <div class="container">
            <button class="btn-export" onclick="exportTableToCSV('reservas_moscu.csv')">💾 EXPORTAR EXCEL</button>
            <h1>🦁 MOSCU Access Control</h1>
            <table>
                <thead>
                    <tr><th>ID</th><th>Hora</th><th>WhatsApp</th><th>Nombre</th><th>Tipo</th><th>Pax</th><th>RRPP</th></tr>
                </thead>
                <tbody>{filas}</tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return html
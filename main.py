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

# --- CONFIGURACIÓN DATABASE (Igual que antes) ---
# Usamos la variable de entorno o un fallback local para pruebas
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:password@localhost/dbname")
# Fix para Render (postgres:// -> postgresql://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELO DE BASE DE DATOS (ACTUALIZADO V2) ---
class Reserva(Base):
    __tablename__ = "reservas_v2"  # <--- CAMBIO DE NOMBRE PARA FORZAR TABLA NUEVA LIMPIA
    
    id = Column(Integer, primary_key=True, index=True)
    whatsapp_id = Column(String, index=True)
    nombre_completo = Column(String)
    tipo_entrada = Column(String) # General o Mesa VIP
    cantidad = Column(Integer)
    confirmada = Column(Boolean, default=False)
    fecha_reserva = Column(DateTime, default=datetime.datetime.utcnow)
    rrpp_asignado = Column(String, default="Organico") # <--- NUEVA COLUMNA DE NEGOCIO

# Crear las tablas
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()

# --- DATOS DE LOS RRPP (SIMULACIÓN DE CARTERA DE CLIENTES) ---
# En un sistema real, esto vendría de otra tabla de base de datos.
DIRECTORIO_RRPP = {
    "matias": {"nombre": "Matias (RRPP)", "celular": "5491111111111"},
    "sofia":  {"nombre": "Sofia (RRPP)", "celular": "5491122222222"},
    "general": {"nombre": "Soporte General", "celular": "5491133333333"} # Default
}

# --- MEMORIA TEMPORAL ---
conversational_state = {}
temp_data = {}
# Memoria de atribución (Para recordar de quién es cliente aunque pasen dias)
user_attribution = {} 

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
            # Query compleja para impresionar al programador: Conteo por RRPP
            msg.body(f"📊 *REPORTE TÉCNICO*\n\nTickets: {total_reservas}\nPax Total: {total_personas}\n\n*System Status:* Online ✅")
            return Response(content=str(resp), media_type="application/xml")
        elif "reset" in incoming_msg:
            db.query(Reserva).delete()
            db.commit()
            msg.body("🗑️ *Database Flush Complete*\nTabla 'reservas_v2' truncada.")
            return Response(content=str(resp), media_type="application/xml")
    # --- FIN ADMIN ---

    # --- LÓGICA DE DEEP LINKING (ATRIBUCIÓN) ---
    # Detectamos si el usuario entra con un link de referido tipo "Hola vengo de Matias"
    rrpp_detectado = "Organico"
    
    if "vengo de" in incoming_msg:
        # Ejemplo: "hola vengo de matias" -> separamos la última palabra
        partes = incoming_msg.split("vengo de ")
        if len(partes) > 1:
            posible_nombre = partes[1].strip().split(" ")[0] # Tomamos el nombre
            if posible_nombre in DIRECTORIO_RRPP:
                user_attribution[sender] = posible_nombre # ¡Sticky Session guardada!
                rrpp_detectado = posible_nombre
                # Reseteamos el mensaje para que el bot salude normal
                state = 'start'
                # Guardamos el dato temporalmente para el saludo personalizado
                temp_data[sender] = {'rrpp_origen': posible_nombre}
    
    # Recuperamos la atribución si ya existía
    if sender in user_attribution:
        rrpp_detectado = user_attribution[sender]

    # --- MÁQUINA DE ESTADOS ---
    state = conversational_state.get(sender, 'start')

    if state == 'start':
        # --- LÓGICA FOMO + FLYER ---
        total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
        cupo_maximo = 150 
        url_flyer = "https://i.ibb.co/mFG17TST/Imagen-Bohemian-Demo.jpg" 

        # Saludo Personalizado si viene de alguien
        saludo_extra = ""
        if sender in temp_data and 'rrpp_origen' in temp_data[sender]:
            nombre_rrpp = DIRECTORIO_RRPP[temp_data[sender]['rrpp_origen']]['nombre']
            saludo_extra = f"👋 ¡Te envía *{nombre_rrpp}*!\n"

        if total_pax >= cupo_maximo:
             msg.body("⛔ *SOLD OUT* ⛔\n\nCapacidad máxima alcanzada.\nGracias por tu interés.")
        
        elif total_pax > (cupo_maximo - 20): 
             msg.body(f"{saludo_extra}🔥 *¡Últimos lugares en MOSCU!* 🔥\n\nQuedan {cupo_maximo - total_pax} cupos.\n\n1. 🎫 Entrada General (con QR)\n2. 🍾 Mesa VIP (Lista Exclusiva)\n3. 🙋 Ayuda Humana (RRPP)")
             msg.media(url_flyer)
             conversational_state[sender] = 'choosing_option'
        else:
             msg.body(f"{saludo_extra}¡Hola! Bienvenid@ a *MOSCU*.\n\n¿Qué querés hacer hoy?\n\n1. 🎫 Entrada General (con QR)\n2. 🍾 Mesa VIP (Lista Exclusiva)\n3. 🙋 Ayuda Humana (RRPP)")
             msg.media(url_flyer) 
             conversational_state[sender] = 'choosing_option'

    elif state == 'choosing_option':
        if incoming_msg == '1':
            temp_data[sender] = {'tipo': 'General', 'nombres_invitados': [], 'rrpp': rrpp_detectado}
            msg.body("🎫 *Entrada General*\n\n¿Cuántas entradas necesitás?\n\nEnviá solo el número.")
            conversational_state[sender] = 'general_cantidad'
            
        elif incoming_msg == '2':
            temp_data[sender] = {'tipo': 'Mesa VIP', 'rrpp': rrpp_detectado}
            msg.body("🍾 *Mesa VIP*\n\nBuenísimo. ¿A nombre de quién reservamos la mesa?")
            conversational_state[sender] = 'vip_nombre'
            
        elif incoming_msg == '3':
            # --- OPCIÓN B: STICKY SESSION HANDOFF ---
            rrpp_usuario = user_attribution.get(sender, 'general') # Si no tiene, va a general
            datos_contacto = DIRECTORIO_RRPP.get(rrpp_usuario, DIRECTORIO_RRPP['general'])
            
            link_wa = f"https://wa.me/{datos_contacto['celular']}?text=Hola,%20necesito%20ayuda%20con%20una%20reserva"
            
            msg.body(f"📞 *Derivación Inteligente*\n\nTe estamos conectando con tu RRPP asignado: *{datos_contacto['nombre']}*.\n\nHacé clic acá para chatear directo:\n👉 {link_wa}")
            # Reseteamos para que no se quede trabado
            conversational_state[sender] = 'start'
            
        else:
            msg.body("Por favor, respondé con '1', '2' o '3'.")

    # --- CAMINO GENERAL ---
    elif state == 'general_cantidad':
        if incoming_msg.isdigit():
            cantidad = int(incoming_msg)
            if cantidad > 10:
                msg.body("El máximo por compra es 10 entradas.\n\nEnviá una cantidad menor.")
            elif cantidad > 0:
                # Aseguramos que temp_data exista
                if sender not in temp_data: temp_data[sender] = {}
                temp_data[sender]['total_esperado'] = cantidad
                
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
            msg.body(f"Listo.\n\nAhora escribí el *Nombre y Apellido* de la persona nº {len(nombres) + 1}:")
        else:
            msg.body("⏳ Procesando tus entradas…\n\nTe van a llegar los QRs uno por uno.")
            
            # Recuperamos el RRPP asignado
            rrpp_final = data.get('rrpp', 'Organico')

            for nombre_invitado in nombres:
                nueva_reserva = Reserva(
                    whatsapp_id=sender,
                    nombre_completo=nombre_invitado,
                    tipo_entrada="General",
                    cantidad=1,
                    confirmada=True,
                    rrpp_asignado=rrpp_final # <--- GUARDAMOS LA ATRIBUCIÓN
                )
                db.add(nueva_reserva)
                db.commit()
                
                datos_safe = urllib.parse.quote(f"ID:{nueva_reserva.id}|{nombre_invitado}|ACCESO:GENERAL")
                url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={datos_safe}"
                
                mensaje_individual = resp.message(f"✅ Entrada para: *{nombre_invitado}*\nID: {nueva_reserva.id}")
                mensaje_individual.media(url_qr)
            
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            
            return Response(content=str(resp), media_type="application/xml")

    # --- CAMINO VIP ---
    elif state == 'vip_nombre':
        temp_data[sender]['nombre'] = Body
        msg.body(f"Bienvenido {Body}.\n\n¿Para cuántas personas es la mesa aprox?\n\n(Solo para organizarnos)")
        conversational_state[sender] = 'vip_cantidad'

    elif state == 'vip_cantidad':
        if incoming_msg.isdigit():
            cantidad = int(incoming_msg)
            data = temp_data.get(sender)
            rrpp_final = data.get('rrpp', 'Organico')
            
            nueva_reserva = Reserva(
                whatsapp_id=sender,
                nombre_completo=data.get('nombre') + " (MESA VIP)",
                tipo_entrada="Mesa VIP",
                cantidad=cantidad,
                confirmada=True,
                rrpp_asignado=rrpp_final # <--- GUARDAMOS LA ATRIBUCIÓN
            )
            db.add(nueva_reserva)
            db.commit()
            
            conversational_state[sender] = 'start'
            temp_data[sender] = {}

            msg.body(f"🥂 *MESA CONFIRMADA*\nTitular: {nueva_reserva.nombre_completo}\nPersonas: {cantidad}\nRRPP: {rrpp_final}\n\n✅ Ya estás en la Lista Exclusiva.\n\nAl llegar, avisá en puerta VIP tu nombre y te indican el ingreso.")
        else:
            msg.body("Ingresa solo números.")

    return Response(content=str(resp), media_type="application/xml")

# --- PANEL DE CONTROL V2 (CON COLUMNA RRPP) ---
@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    
    filas = ""
    for r in reservas:
        color = '#e3f2fd' if r.tipo_entrada == 'General' else '#fff3e0'
        estilo_borde = 'border-left: 5px solid gold;' if r.tipo_entrada == 'Mesa VIP' else ''
        
        # Color para el RRPP
        estilo_rrpp = "color: #2ecc71; font-weight: bold;" if r.rrpp_asignado != "Organico" else "color: #95a5a6;"

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
            <td style="padding: 10px; border-bottom: 1px solid #ddd; {estilo_rrpp}">{r.rrpp_asignado}</td>
        </tr>
        """
    
    html = f"""
    <html>
        <head>
            <title>Panel MOSCU V2</title>
            <meta http-equiv="refresh" content="5"> 
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                h1 {{ color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th {{ text-align: left; padding: 15px 10px; background: #f8f9fa; color: #666; font-weight: 600; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📋 Control de Accesos & Atribución RRPP</h1>
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Hora</th>
                            <th>Nombre / Titular</th>
                            <th>Acceso</th>
                            <th>Pax</th>
                            <th>Referido Por (RRPP)</th>
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
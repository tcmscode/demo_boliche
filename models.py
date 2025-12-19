from sqlalchemy import Column, Integer, String, DateTime, Boolean
from database import Base
import datetime

class Reserva(Base):
    __tablename__ = "reservas"

    id = Column(Integer, primary_key=True, index=True)
    whatsapp_id = Column(String, index=True) # El número de teléfono
    nombre_completo = Column(String)
    tipo_entrada = Column(String) # 'General' o 'Mesa VIP'
    cantidad = Column(Integer)
    fecha_reserva = Column(DateTime, default=datetime.datetime.utcnow)
    confirmada = Column(Boolean, default=False)
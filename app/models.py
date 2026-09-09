from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base


class Pallet(Base):
    __tablename__ = "pallets"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(100), unique=True, nullable=False, index=True)
    delivery_date = Column(Date, nullable=False)
    purchase_gross = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    shoes = relationship("Shoe", back_populates="pallet", cascade="all, delete-orphan")


class Shoe(Base):
    __tablename__ = "shoes"

    id = Column(Integer, primary_key=True, index=True)
    pallet_id = Column(Integer, ForeignKey("pallets.id", ondelete="CASCADE"), nullable=False)
    internal_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="available", index=True)
    sale_price = Column(Float, nullable=True)
    sale_date = Column(Date, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    pallet = relationship("Pallet", back_populates="shoes")
    photos = relationship("ShoePhoto", back_populates="shoe", cascade="all, delete-orphan")


class ShoePhoto(Base):
    __tablename__ = "shoe_photos"

    id = Column(Integer, primary_key=True, index=True)
    shoe_id = Column(Integer, ForeignKey("shoes.id", ondelete="CASCADE"), nullable=False)
    file_path = Column(String(1000), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    shoe = relationship("Shoe", back_populates="photos")


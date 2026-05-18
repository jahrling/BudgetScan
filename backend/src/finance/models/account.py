from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from finance.models.base import Base


class Account(Base):
    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))
    quicken_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

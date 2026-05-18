from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from finance.models.base import Base


class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))

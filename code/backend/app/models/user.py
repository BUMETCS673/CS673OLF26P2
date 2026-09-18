"""The `users` table."""

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.base import iso, utcnow


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    # unique=True alone gives a named UNIQUE constraint (with its own index behind it).
    # Adding index=True as well would swap that for a bare unique index, which enforces
    # the same thing but is harder for WS1 to recognise when turning the IntegrityError
    # from a duplicate registration into a 409.
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    decks = db.relationship(
        "Deck",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @staticmethod
    def normalize_email(email: str) -> str:
        """Trim and lowercase, so Miles@BU.edu and miles@bu.edu are one account."""
        return (email or "").strip().lower()

    def set_password(self, password: str) -> None:
        """Store the hash. The plain password is never written to the database."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password or "")

    def to_dict(self) -> dict:
        """The `User` shape from the API contract. There is no password field, ever."""
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "created_at": iso(self.created_at),
        }

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email}>"

import datetime

from rhub.api import db


class ModelMixin:
    """Datatabase model mixin with methods useful in REST API endpoints."""

    def to_dict(self):
        """Covert to `dict`."""
        data = {}
        for column in self.__table__.columns:
            data[column.name] = getattr(self, column.name)
        return data

    @classmethod
    def from_dict(cls, data):
        """Create from `dict`."""
        return cls(**data)

    def update_from_dict(self, data):
        """Update from `dict`."""
        for k, v in data.items():
            setattr(self, k, v)


def date_now():
    return datetime.datetime.now().astimezone(datetime.timezone.utc)


def db_sort(query, sort_by):
    direction = 'DESC' if sort_by.startswith('-') else 'ASC'
    column = sort_by.removeprefix('-')
    return query.order_by(db.text(f'{column} {direction}'))

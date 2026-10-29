from flask import Blueprint

bp = Blueprint("management", __name__, url_prefix="/manage")

from app.management import routes

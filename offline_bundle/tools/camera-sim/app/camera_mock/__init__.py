from flask import Blueprint

cycctv_bp = Blueprint(
    'cycctv',
    __name__,
    url_prefix='/api/v1/camera',
    template_folder='../templates'
)

from . import routes  # noqa: E402, F401

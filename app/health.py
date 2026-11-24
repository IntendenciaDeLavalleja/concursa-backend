from flask import Blueprint, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db

health_bp = Blueprint('health', __name__)


@health_bp.route('/health', methods=['GET'])
def health():
    try:
        db.session.execute(text('SELECT 1'))
    except SQLAlchemyError:
        return jsonify({'status': 'unavailable'}), 503

    return jsonify({'status': 'ok'}), 200

from flask import Blueprint, jsonify
import db
from models.risk_register import RiskRegister

risks_bp = Blueprint('risks', __name__)

@risks_bp.route('', methods=['GET'])
@risks_bp.route('/', methods=['GET'])
def get_risks():
    risks = db.db_session.query(RiskRegister).all()
    result = [r.to_dict() for r in risks]
    return jsonify(result)

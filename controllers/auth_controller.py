from flask import Blueprint, request, jsonify
from services.auth_service import AuthService
import db
from models.user import User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    role = data.get('role', 'Investor')
    
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
        
    existing = db.db_session.query(User).filter_by(email=email).first()
    if existing:
        return jsonify({"error": "User already exists"}), 400
        
    from werkzeug.security import generate_password_hash
    hashed_pw = generate_password_hash(password)
    user = User(email=email, password_hash=hashed_pw, role=role)
    db.db_session.add(user)
    db.db_session.commit()
    
    return jsonify({"message": "User registered successfully", "user": user.to_dict()}), 201

from werkzeug.security import check_password_hash

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    user = db.db_session.query(User).filter_by(email=email).first()
    
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid credentials"}), 401
        
    token = AuthService.generate_token(user.role, str(user.id))
    return jsonify({"token": token, "role": user.role, "email": user.email})

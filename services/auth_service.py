import jwt
import datetime
from config import Config

class AuthService:
    """
    Handles JWT generation and verification.
    """
    @staticmethod
    def generate_token(role: str, user_id: str = "demo_user") -> str:
        payload = {
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1),
            'iat': datetime.datetime.utcnow(),
            'sub': user_id,
            'role': role
        }
        return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')

    @staticmethod
    def decode_token(token: str) -> dict:
        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            raise Exception('Token expired. Please log in again.')
        except jwt.InvalidTokenError:
            raise Exception('Invalid token. Please log in again.')


def require_roles(*allowed_roles):
    """
    Decorator that checks Authorization Bearer token in request headers,
    decodes it using AuthService.decode_token, and verifies user role.
    Returns 401 if missing/invalid, 403 if role is not permitted.
    """
    from functools import wraps
    from flask import request, jsonify

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get('Authorization')
            if not auth_header:
                return jsonify({"error": "Unauthorized: Missing Authorization header"}), 401
            
            parts = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != 'bearer':
                return jsonify({"error": "Unauthorized: Invalid Authorization header format"}), 401
            
            token = parts[1]
            try:
                payload = AuthService.decode_token(token)
            except Exception as e:
                return jsonify({"error": f"Unauthorized: {str(e)}"}), 401
            
            user_role = payload.get('role')
            if user_role not in allowed_roles:
                return jsonify({
                    "error": f"Forbidden: Access restricted to {', '.join(allowed_roles)}. Your role is '{user_role}'."
                }), 403
            
            request.user = payload
            return f(*args, **kwargs)
        return decorated_function
    return decorator

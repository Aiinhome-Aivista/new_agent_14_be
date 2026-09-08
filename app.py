from flask import Flask
from flask_cors import CORS
from config import Config
from db import init_db
from controllers.auth_controller import auth_bp
from controllers.ingestion_controller import ingestion_bp
from controllers.chat_controller import chat_bp
from controllers.dashboard_controller import dashboard_bp
from controllers.reports_controller import reports_bp
from controllers.risks_controller import risks_bp

from controllers.settings_controller import settings_bp
from controllers.guardrails_controller import guardrails_bp
from controllers.knowledge_controller import knowledge_bp

def create_app():
    app = Flask(__name__)
    CORS(app, supports_credentials=True)
    app.config.from_object(Config)

    # Initialize Database
    init_db(app)

    # Ensure IntegrationSetting is known before create_all
    from models.integration_setting import IntegrationSetting
    import db
    db.Base.metadata.create_all(bind=db.engine)

    # Register Blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(ingestion_bp, url_prefix='/api/ingestion')
    app.register_blueprint(chat_bp, url_prefix='/api/chat')
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(reports_bp, url_prefix='/api/reports')
    app.register_blueprint(risks_bp, url_prefix='/api/risks')
    app.register_blueprint(settings_bp, url_prefix='/api/settings')
    app.register_blueprint(guardrails_bp, url_prefix='/api/guardrails')
    app.register_blueprint(knowledge_bp, url_prefix='/api/knowledge')

    @app.route('/health', methods=['GET'])
    def health_check():
        return {'status': 'healthy', 'message': 'VPM Backend is running'}, 200

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=app.config['FLASK_DEBUG'])

from flask import Blueprint, Response, request
from services.chat_service import ChatService

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/stream', methods=['GET'])
def chat_stream():
    query = request.args.get('query', 'Hello')
    project_id = request.args.get('project_id')
    return Response(ChatService.stream_chat(query, project_id=project_id), mimetype='text/event-stream')

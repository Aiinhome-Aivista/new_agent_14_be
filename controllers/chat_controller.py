from flask import Blueprint, Response, request
from services.chat_service import ChatService

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/stream', methods=['GET'])
def chat_stream():
    query = request.args.get('query', 'Hello')
    return Response(ChatService.stream_chat(query), mimetype='text/event-stream')

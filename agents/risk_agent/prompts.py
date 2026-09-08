import os

def get_risk_system_prompt():
    filepath = os.path.join(os.path.dirname(__file__), '..', '..', 'prompts', 'risk_system_prompt.txt')
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def get_risk_user_prompt():
    filepath = os.path.join(os.path.dirname(__file__), '..', '..', 'prompts', 'risk_user_prompt.txt')
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

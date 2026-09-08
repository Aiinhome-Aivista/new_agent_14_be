import os

def get_financial_system_prompt():
    filepath = os.path.join(os.path.dirname(__file__), '..', '..', 'prompts', 'financial_system_prompt.txt')
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

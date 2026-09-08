import os

def get_predictive_system_prompt():
    filepath = os.path.join(os.path.dirname(__file__), '..', '..', 'prompts', 'predictive_system_prompt.txt')
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

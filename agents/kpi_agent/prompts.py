import os

def get_kpi_system_prompt():
    filepath = os.path.join(os.path.dirname(__file__), '..', '..', 'prompts', 'kpi_system_prompt.txt')
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

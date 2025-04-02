import os
import json
from typing import Dict, Any, Optional

def save_config(config: Dict[str, Any], filename: str = "config.json") -> bool:
    """Збереження налаштувань у файл."""
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Помилка збереження конфігурації: {e}")
        return False

def load_config(filename: str = "config.json") -> Optional[Dict[str, Any]]:
    """Завантаження налаштувань з файлу."""
    try:
        if not os.path.exists(filename):
            return None
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Помилка завантаження конфігурації: {e}")
        return None
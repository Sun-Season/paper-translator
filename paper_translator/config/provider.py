"""按服务地址选择密钥，防止把其他服务的密钥发送给 DeepSeek。"""
import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import dotenv_values

DEFAULT_MODEL = 'deepseek-flash'
DEFAULT_BASE_URL = 'https://api.deepseek.com'

def api_key(base_url):
    if urlparse(base_url).hostname == 'api.deepseek.com':
        path=Path(__file__).resolve().parents[2]/'.env.deepseek.local'
        return os.getenv('DEEPSEEK_API_KEY') or dotenv_values(path).get('DEEPSEEK_API_KEY')
    return os.getenv('OPENAI_API_KEY')

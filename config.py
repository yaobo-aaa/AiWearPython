import os

from dotenv import load_dotenv

# 读取 .env 中的配置
load_dotenv()
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

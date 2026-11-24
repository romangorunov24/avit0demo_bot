import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "1"
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["TZ_NAME"] = "Europe/Moscow"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

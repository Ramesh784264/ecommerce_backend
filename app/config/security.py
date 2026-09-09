from dotenv import load_dotenv
import os

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")

# .env la values missing-a irundha, clear error message kudukum
if not SECRET_KEY:
    raise ValueError("SECRET_KEY not found in .env file")
if not ALGORITHM:
    raise ValueError("ALGORITHM not found in .env file")
if not ACCESS_TOKEN_EXPIRE_MINUTES:
    raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES not found in .env file")

ACCESS_TOKEN_EXPIRE_MINUTES = int(ACCESS_TOKEN_EXPIRE_MINUTES)

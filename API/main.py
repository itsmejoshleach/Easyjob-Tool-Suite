import easyjob as ej
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

EJ_Username = os.getenv('EJ_Username')
EJ_Password = os.getenv('EJ_Password')
EJ_Base_URL = os.getenv('EJ_Base_URL')

# Connect & authenticate (ignoring SSL for testing)
ej.quick_login(
    base_url=EJ_Base_URL,
    username=EJ_Username,
    password=EJ_Password,
    verify_cert=False
)

print(ej.test_connection())

ej.print_items_in_job('3148.03')
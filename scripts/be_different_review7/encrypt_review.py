import os,json,base64
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django;django.setup()
from apps.publisher.models import MobileApp
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import padding
a=MobileApp.objects.get(slug="be-different")
key=serialization.load_pem_public_key("-----BEGIN PUBLIC KEY-----\nMIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAtBhsEy/s3nMM9fqFdO9A\n1AZeYDIJ4Ybbi2cf8r+iohA935wDK2DIc4BC2tuL2/BseHHtVcoFQijDxKj6gSuj\n1v9rg10Pos3o7dnOc2GgqUpGEgdhi0Y7dxSo+6zxJLur45lOOmNPBGGZsIs9sMkl\nEikUPXATJRHETVBYFOFJNbAG8dquuEiSjQzCWFVAbIQQLrCOSgO28Gc0pvLYatvw\nO4t2Ctvr5vEOH6XEuaXpa5EU5W8nHofvyFMlBWrKY93NcIT764boNa3Gt5W6x3k4\na5oQab91QdegvdOWFxY0HYyGkzmHs336DENrM/nSozpudNVy6EypNnywDI1690Tm\n4fwlli6pYpySywsBzAZoVu0ys5MZFt32TEIFkSNaln9q/KT9K77TMHKq4aVOGoyQ\ncV7aqnXlzmu9LLFGevo/dyxnyYzo+biPLAIuliRZliQbwx9s06tIkl0DNzjslmUN\nzs32Xt9kFUYyfdmdBqQHCRxBLg0ZB8k93T626oq83m4TAgMBAAE=\n-----END PUBLIC KEY-----".encode())
payload=json.dumps({"username":a.review_username,"password":a.get_review_password()}).encode()
print("REVIEW_ENCRYPTED="+base64.b64encode(key.encrypt(payload,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))).decode())

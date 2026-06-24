from app.core.security import(hash_password,verify_password,create_access_token,decode_access_token)


h = hash_password("test1234!")
assert verify_password("test1234!",h) is True
assert verify_password("wrong",h) is False

token = create_access_token("1")
payload = decode_access_token(token)
assert payload.sub == "1"

print("5단계 완료")
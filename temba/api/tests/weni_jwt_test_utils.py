import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings


def generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


class WeniJWTTestMixin:
    """Shared RSA key pair and helpers for weni_commons JWT auth tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._jwt_private_pem, cls._jwt_public_pem = generate_rsa_keypair()
        cls._jwt_settings = override_settings(JWT_PUBLIC_KEY=cls._jwt_public_pem)
        cls._jwt_settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls._jwt_settings.disable()
        super().tearDownClass()

    def sign_internal_jwt(self, **claims):
        payload = {"can_communicate_internally": True}
        payload.update(claims)
        return jwt.encode(payload, self._jwt_private_pem, algorithm="RS256")

    def jwt_headers(self, **claims):
        return {"HTTP_X_WENI_AUTH": self.sign_internal_jwt(**claims)}

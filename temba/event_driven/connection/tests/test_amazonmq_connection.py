from unittest import TestCase
from unittest.mock import MagicMock, patch

from weni.pika_eda.connection_params import PikaConnectionParams

from temba.event_driven.connection.amazonmq_connection import AmazonMQConnectionFactory


def _make_settings(**overrides):
    """Build a mock Django settings object with sensible AmazonMQ defaults."""
    defaults = {
        "PIKA_EDA_BROKER_HOST": "broker.amazonmq.test",
        "PIKA_EDA_BROKER_USER": "admin",
        "PIKA_EDA_BROKER_PASSWORD": "secret",
    }
    defaults.update(overrides)

    settings = MagicMock()
    settings.configure_mock(**defaults)

    def _getattr(name, default=None):
        try:
            return getattr(settings, name)
        except AttributeError:
            return default

    settings.__class__ = type("Settings", (), {"__getattr__": lambda s, n: _getattr(n)})
    return settings


class AmazonMQConnectionFactoryTestCase(TestCase):
    """Unit tests for AmazonMQConnectionFactory."""

    @patch("temba.event_driven.connection.amazonmq_connection.settings")
    @patch.object(PikaConnectionParams, "create_ssl_options")
    def test_returns_params_with_ssl_enabled_by_default(self, mock_ssl, mock_settings):
        mock_settings.PIKA_EDA_BROKER_HOST = "broker.test"
        mock_settings.PIKA_EDA_BROKER_USER = "user"
        mock_settings.PIKA_EDA_BROKER_PASSWORD = "pass"
        mock_ssl.return_value = MagicMock(name="ssl_options")

        # no PIKA_EDA_SSL_ENABLED set → defaults to True
        def side_getattr(name, default=None):
            mapping = {
                "PIKA_EDA_SSL_ENABLED": True,
                "PIKA_EDA_SSL_CERT_PATH": None,
                "PIKA_EDA_SSL_KEY_PATH": None,
                "PIKA_EDA_SSL_CA_CERTS": None,
                "PIKA_EDA_SSL_SERVER_HOSTNAME": None,
                "PIKA_EDA_BROKER_PORT": 5671,
                "PIKA_EDA_VIRTUAL_HOST": "/",
            }
            if name in mapping:
                return mapping[name]
            return default

        mock_settings.__class__ = type("FakeSettings", (), {})
        type(mock_settings).__getattr__ = lambda self, name: side_getattr(name)

        params = AmazonMQConnectionFactory.get_params()

        self.assertIsInstance(params, PikaConnectionParams)
        self.assertEqual(params.host, "broker.test")
        self.assertEqual(params.port, 5671)
        self.assertEqual(params.userid, "user")
        self.assertEqual(params.password, "pass")
        self.assertIsNotNone(params.ssl_options)
        mock_ssl.assert_called_once()

    @patch("temba.event_driven.connection.amazonmq_connection.settings")
    def test_returns_params_without_ssl_when_disabled(self, mock_settings):
        mock_settings.PIKA_EDA_BROKER_HOST = "broker.test"
        mock_settings.PIKA_EDA_BROKER_USER = "user"
        mock_settings.PIKA_EDA_BROKER_PASSWORD = "pass"

        def side_getattr(name, default=None):
            mapping = {
                "PIKA_EDA_SSL_ENABLED": False,
                "PIKA_EDA_SSL_CERT_PATH": None,
                "PIKA_EDA_SSL_KEY_PATH": None,
                "PIKA_EDA_SSL_CA_CERTS": None,
                "PIKA_EDA_SSL_SERVER_HOSTNAME": None,
                "PIKA_EDA_BROKER_PORT": 5672,
                "PIKA_EDA_VIRTUAL_HOST": "/",
            }
            if name in mapping:
                return mapping[name]
            return default

        mock_settings.__class__ = type("FakeSettings", (), {})
        type(mock_settings).__getattr__ = lambda self, name: side_getattr(name)

        params = AmazonMQConnectionFactory.get_params()

        self.assertIsInstance(params, PikaConnectionParams)
        self.assertEqual(params.port, 5672)
        self.assertIsNone(params.ssl_options)

    @patch("temba.event_driven.connection.amazonmq_connection.settings")
    @patch.object(PikaConnectionParams, "create_ssl_options")
    def test_custom_port_is_respected(self, mock_ssl, mock_settings):
        mock_settings.PIKA_EDA_BROKER_HOST = "broker.test"
        mock_settings.PIKA_EDA_BROKER_USER = "user"
        mock_settings.PIKA_EDA_BROKER_PASSWORD = "pass"
        mock_ssl.return_value = MagicMock()

        def side_getattr(name, default=None):
            mapping = {
                "PIKA_EDA_SSL_ENABLED": True,
                "PIKA_EDA_SSL_CERT_PATH": None,
                "PIKA_EDA_SSL_KEY_PATH": None,
                "PIKA_EDA_SSL_CA_CERTS": None,
                "PIKA_EDA_SSL_SERVER_HOSTNAME": None,
                "PIKA_EDA_BROKER_PORT": 5673,
                "PIKA_EDA_VIRTUAL_HOST": "/custom",
            }
            if name in mapping:
                return mapping[name]
            return default

        mock_settings.__class__ = type("FakeSettings", (), {})
        type(mock_settings).__getattr__ = lambda self, name: side_getattr(name)

        params = AmazonMQConnectionFactory.get_params()

        self.assertEqual(params.port, 5673)
        self.assertEqual(params.virtual_host, "/custom")

    @patch("temba.event_driven.connection.amazonmq_connection.settings")
    @patch.object(PikaConnectionParams, "create_ssl_options")
    def test_ssl_options_forward_cert_paths(self, mock_ssl, mock_settings):
        mock_settings.PIKA_EDA_BROKER_HOST = "broker.test"
        mock_settings.PIKA_EDA_BROKER_USER = "user"
        mock_settings.PIKA_EDA_BROKER_PASSWORD = "pass"
        mock_ssl.return_value = MagicMock()

        def side_getattr(name, default=None):
            mapping = {
                "PIKA_EDA_SSL_ENABLED": True,
                "PIKA_EDA_SSL_CERT_PATH": "/certs/client.pem",
                "PIKA_EDA_SSL_KEY_PATH": "/certs/client.key",
                "PIKA_EDA_SSL_CA_CERTS": "/certs/ca.pem",
                "PIKA_EDA_SSL_SERVER_HOSTNAME": "custom.host",
                "PIKA_EDA_BROKER_PORT": 5671,
                "PIKA_EDA_VIRTUAL_HOST": "/",
            }
            if name in mapping:
                return mapping[name]
            return default

        mock_settings.__class__ = type("FakeSettings", (), {})
        type(mock_settings).__getattr__ = lambda self, name: side_getattr(name)

        AmazonMQConnectionFactory.get_params()

        mock_ssl.assert_called_once_with(
            ca_certs="/certs/ca.pem",
            certfile="/certs/client.pem",
            keyfile="/certs/client.key",
            server_hostname="custom.host",
            host="broker.test",
        )

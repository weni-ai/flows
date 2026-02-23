from weni.pika_eda.connection_params import PikaConnectionParams, PikaParamsFactory

from django.conf import settings


class AmazonMQConnectionFactory(PikaParamsFactory):
    """
    Factory that builds PikaConnectionParams for AmazonMQ from Django settings.
    AmazonMQ speaks AMQP over TLS, so SSL is enabled by default.

    Required Django settings:
        PIKA_EDA_BROKER_HOST     – AmazonMQ broker endpoint
        PIKA_EDA_BROKER_USER     – broker username
        PIKA_EDA_BROKER_PASSWORD – broker password

    Optional Django settings:
        PIKA_EDA_BROKER_PORT          – default 5671 (AMQPS)
        PIKA_EDA_VIRTUAL_HOST         – default "/"
        PIKA_EDA_SSL_ENABLED          – default True
        PIKA_EDA_SSL_CERT_PATH        – client certificate file
        PIKA_EDA_SSL_KEY_PATH         – client key file
        PIKA_EDA_SSL_CA_CERTS         – CA certificate file
        PIKA_EDA_SSL_SERVER_HOSTNAME  – hostname for SSL verification
    """

    @classmethod
    def get_params(cls) -> PikaConnectionParams:
        ssl_options = None

        ssl_enabled = getattr(settings, "PIKA_EDA_SSL_ENABLED", True)
        ssl_cert_path = getattr(settings, "PIKA_EDA_SSL_CERT_PATH", None)
        ssl_key_path = getattr(settings, "PIKA_EDA_SSL_KEY_PATH", None)
        ssl_ca_certs = getattr(settings, "PIKA_EDA_SSL_CA_CERTS", None)
        ssl_server_hostname = getattr(settings, "PIKA_EDA_SSL_SERVER_HOSTNAME", None)

        host = settings.PIKA_EDA_BROKER_HOST

        if ssl_enabled or ssl_cert_path or ssl_ca_certs:
            ssl_options = PikaConnectionParams.create_ssl_options(
                ca_certs=ssl_ca_certs,
                certfile=ssl_cert_path,
                keyfile=ssl_key_path,
                server_hostname=ssl_server_hostname,
                host=host,
            )

        port = getattr(settings, "PIKA_EDA_BROKER_PORT", 5671 if ssl_options else 5672)

        return PikaConnectionParams(
            host=host,
            port=port,
            userid=settings.PIKA_EDA_BROKER_USER,
            password=settings.PIKA_EDA_BROKER_PASSWORD,
            virtual_host=getattr(settings, "PIKA_EDA_VIRTUAL_HOST", "/"),
            ssl_options=ssl_options,
        )

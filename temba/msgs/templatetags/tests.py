from urllib.parse import parse_qs, urlparse

from django.template import Context, Template
from django.test import override_settings

from temba.tests import TembaTest
from temba.tests.s3 import S3_SIGNING_SETTINGS

from .sms import attachment_button


class TestSMSTagLibrary(TembaTest):
    def test_attachment_button(self):
        # complete attachment with subtype and extension
        self.assertEqual(
            {
                "content_type": "image/jpeg",
                "category": "image",
                "preview": "JPEG",
                "url": "https://example.com/test.jpg",
                "download_url": "https://example.com/test.jpg",
                "is_playable": False,
            },
            attachment_button("image/jpeg:https://example.com/test.jpg"),
        )

        # missing extension and thus no subtype
        self.assertEqual(
            {
                "content_type": "image",
                "category": "image",
                "preview": "IMAGE",
                "url": "https://example.com/test.aspx",
                "download_url": "https://example.com/test.aspx",
                "is_playable": False,
            },
            attachment_button("image:https://example.com/test.aspx"),
        )

        # ogg file with wrong content type
        self.assertEqual(
            {
                "content_type": "audio/ogg",
                "category": "audio",
                "preview": "OGG",
                "url": "https://example.com/test.ogg",
                "download_url": "https://example.com/test.ogg",
                "is_playable": True,
            },
            attachment_button("application/octet-stream:https://example.com/test.ogg"),
        )

        # oga file with wrong content type and a query string
        self.assertEqual(
            {
                "content_type": "audio/ogg",
                "category": "audio",
                "preview": "OGG",
                "url": "https://example.com/test.oga?token=123",
                "download_url": "https://example.com/test.oga?token=123",
                "is_playable": True,
            },
            attachment_button("application/octet-stream:https://example.com/test.oga?token=123"),
        )

        # geo coordinates
        self.assertEqual(
            {
                "content_type": "geo",
                "category": "geo",
                "preview": "-35.998287,26.478109",
                "url": "https://www.openstreetmap.org/?mlat=-35.998287&mlon=26.478109#map=18/-35.998287/26.478109",
                "download_url": None,
                "is_playable": False,
            },
            attachment_button("geo:-35.998287,26.478109"),
        )

        # updated geo coordinates
        self.assertEqual(
            {
                "content_type": "geo",
                "category": "geo",
                "preview": "-35.998287,26.478109",
                "url": "https://www.openstreetmap.org/?mlat=-35.998287&mlon=26.478109#map=18/-35.998287/26.478109",
                "download_url": None,
                "is_playable": False,
            },
            attachment_button(
                "geo:-35.998287,26.478109;name:Main Street Beach;address:Main Street Beach, Santa Cruz, CA"
            ),
        )

        context = Context(attachment_button("image/jpeg:https://example.com/test.jpg"))
        template = Template("""{% load sms %}{% attachment_button 'image/jpeg:https://example.com/test.jpg' %}""")
        self.assertIn("openMediaModal", template.render(context))
        self.assertIn("href='https://example.com/test.jpg'", template.render(context))

    @override_settings(**S3_SIGNING_SETTINGS)
    def test_attachment_button_presigns_s3_urls(self):
        button = attachment_button("application/octet-stream:https://media-bucket.s3.amazonaws.com/media/voice.ogg")

        self.assertEqual("audio/ogg", button["content_type"])
        self.assertTrue(button["is_playable"])

        url, download_url = urlparse(button["url"]), urlparse(button["download_url"])
        self.assertEqual("media-bucket.s3.sa-east-1.amazonaws.com", url.hostname)
        self.assertEqual("/media/voice.ogg", url.path)
        self.assertIn("X-Amz-Signature", parse_qs(url.query))
        self.assertNotIn("response-content-disposition", parse_qs(url.query))

        self.assertEqual("/media/voice.ogg", download_url.path)
        self.assertEqual(["attachment"], parse_qs(download_url.query)["response-content-disposition"])

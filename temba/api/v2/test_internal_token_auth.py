from django.urls import reverse

from temba.api.models import APIToken
from temba.api.v2.tests import APITest


class InternalTokenAuthV2Test(APITest):
    def test_internal_token_sets_org_from_project_and_allows_get(self):
        # login without API token (session path simulates internal token path)
        self.login(self.editor)

        # simulate user without current org context
        self.editor.set_org(None)

        # ensure org has proj_uuid
        project_uuid = str(self.org.proj_uuid or "")
        if not project_uuid:
            # fallback in rare cases
            from uuid import uuid4

            self.org.proj_uuid = uuid4()
            self.org.save(update_fields=("proj_uuid",))
            project_uuid = str(self.org.proj_uuid)

        url = reverse("api.v2.messages")
        response = self.fetchJSON(url, query=f"project_uuid={project_uuid}")
        # should be allowed for editor
        self.assertEqual(response.status_code, 200)

    def test_internal_token_missing_project_uuid_without_org_is_forbidden(self):
        self.login(self.editor)

        # remove org context and do not pass project_uuid
        self.editor.set_org(None)

        url = reverse("api.v2.messages")
        response = self.fetchJSON(url)
        # no org and no project_uuid => forbidden by APIPermission
        self.assertEqual(response.status_code, 403)

    def test_api_token_auth_still_works(self):
        token = APIToken.get_or_create(self.org, self.editor)

        url = reverse("api.v2.messages") + ".json"
        response = self.client.get(
            url,
            content_type="application/json",
            HTTP_X_FORWARDED_HTTPS="https",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        self.assertEqual(response.status_code, 200)

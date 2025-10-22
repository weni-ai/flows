import ast
import json
import re

from smartmin.views import SmartFormView

from django import forms
from django.utils.translation import ugettext_lazy as _

from temba.contacts.models import URN

from ...models import Channel
from ...views import ClaimViewMixin


class ClaimView(ClaimViewMixin, SmartFormView):
    class ClaimForm(ClaimViewMixin.Form):
        config = forms.CharField(
            required=False,
            widget=forms.Textarea,
            label=_("Config (JSON)"),
            help_text=_("Arbitrary key/values to store in channel config (JSON object)"),
        )

        schemes = forms.CharField(
            required=False,
            label=_("Schemes (comma-separated)"),
            help_text=_("E.g.: ext, tel, whatsapp. Defaults to ext if omitted."),
        )

        address = forms.CharField(
            required=False,
            label=_("Address"),
            help_text=_("Optional channel address (e.g. external ID or phone number)"),
        )

        name = forms.CharField(
            required=False,
            label=_("Name"),
            help_text=_("Optional channel display name"),
        )

    title = "Connect External API V2"
    permission = "channels.channel_claim"
    success_url = "uuid@channels.channel_configuration"

    def get_form_class(self):
        return ClaimView.ClaimForm

    def form_valid(self, form):
        org = self.request.user.get_org()
        data = form.cleaned_data

        config_text = data.get("config")
        if config_text:
            try:
                parsed = json.loads(config_text)
                if not isinstance(parsed, dict):
                    form.add_error("config", _("JSON must be an object"))
                    return self.form_invalid(form)
                config = parsed
            except Exception:
                form.add_error("config", _("Invalid JSON"))
                return self.form_invalid(form)
        else:
            config = {}
            # Try to parse JSON body (common for API clients). Prefer top-level 'data' key if present
            try:
                body_bytes = getattr(self.request, "body", b"")
                if body_bytes:
                    body_text = body_bytes.decode("utf-8")
                    if body_text:
                        body_obj = json.loads(body_text)
                        if isinstance(body_obj, dict):
                            payload = body_obj.get("data", body_obj)
                            if isinstance(payload, dict):
                                config.update(payload)
            except Exception:
                # ignore if body is not JSON
                pass

            # Also support form-encoded posts with a 'data' JSON field
            nested_data_text = self.request.POST.get("data")
            if nested_data_text:
                try:
                    nested_obj = json.loads(nested_data_text)
                except Exception:
                    try:
                        nested_obj = ast.literal_eval(nested_data_text)
                    except Exception:
                        nested_obj = None
                if isinstance(nested_obj, dict):
                    config.update(nested_obj)

            # Finally, merge any other non-reserved POST keys, reconstructing nested structures from bracketed keys
            reserved = {"csrfmiddlewaretoken", "schemes", "address", "name", "config", "data"}

            def assign_nested(target, tokens, value):
                node = target
                for i, token in enumerate(tokens):
                    is_last = i == len(tokens) - 1
                    next_token = tokens[i + 1] if not is_last else None
                    # numeric tokens indicate list indices
                    if token.isdigit():
                        index = int(token)
                        if not isinstance(node, list):
                            # convert current node to list if needed
                            # replace empty dict with list only if it's empty
                            if isinstance(node, dict):
                                # cannot mutate parent reference easily; use a sentinel: we only call with list context
                                # fallback: store under string index if dict
                                node[str(index)] = value if is_last else {}
                                node = node[str(index)]
                                continue
                            else:
                                return
                        # ensure list is large enough
                        while len(node) <= index:
                            node.append({})
                        if is_last:
                            node[index] = value
                        else:
                            if not isinstance(node[index], (dict, list)):
                                node[index] = {}
                            node = node[index]
                    else:
                        if is_last:
                            if isinstance(node, list):
                                # cannot set dict key on list node; append dict
                                node.append({token: value})
                            else:
                                node[token] = value
                        else:
                            if isinstance(node, list):
                                # append dict and descend
                                new_dict = {}
                                node.append(new_dict)
                                node = new_dict
                            else:
                                # if next token is a digit, initialize as list, otherwise dict
                                if token not in node or not isinstance(node[token], (dict, list)):
                                    node[token] = [] if (next_token and next_token.isdigit()) else {}
                                node = node[token]

            for key in self.request.POST.keys():
                if key in reserved:
                    continue
                values = self.request.POST.getlist(key)
                if not values:
                    continue
                # Choose a single value if only one, else keep the list as-is
                value_to_set = values[0] if len(values) == 1 else [v for v in values if v is not None and v != ""]

                # Detect bracket notation like a[b][0][c]
                tokens = re.findall(r"([^\[\]]+)", key)
                if len(tokens) > 1:
                    # Ensure root exists
                    root = tokens[0]
                    if root not in config or not isinstance(config.get(root), (dict, list)):
                        # initialize as dict by default
                        config[root] = {}
                    assign_nested(config[root], tokens[1:], value_to_set)
                else:
                    # flat key
                    config[key] = value_to_set

        schemes_str = (data.get("schemes") or "").strip()
        if schemes_str:
            schemes = [s.strip() for s in schemes_str.split(",") if s.strip()]
        else:
            schemes = [URN.EXTERNAL_SCHEME]

        address = (data.get("address") or "").strip()
        name = (data.get("name") or "External API V2").strip() or "External API V2"

        self.object = Channel.add_config_external_channel(
            org=org,
            user=self.request.user,
            country=None,
            address=address,
            channel_type=self.channel_type,
            config=config,
            role=Channel.DEFAULT_ROLE,
            schemes=schemes,
            name=name,
        )

        return super().form_valid(form)

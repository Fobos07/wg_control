import ipaddress

from django import forms

from .models import Peer, WGInterface


class BootstrapMixin:
    """Apply Bootstrap form classes to all widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class PeerCreateForm(BootstrapMixin, forms.Form):
    name = forms.CharField(max_length=120, label="Name")
    address = forms.CharField(
        max_length=255,
        required=False,
        label="Tunnel IP",
        help_text="Leave blank to auto-assign the next free address.",
    )
    use_preshared_key = forms.BooleanField(
        required=False, initial=True, label="Generate preshared key"
    )
    client_dns = forms.CharField(
        max_length=255, required=False, label="DNS (override)",
        help_text="Blank = use the interface default.",
    )
    client_allowed_ips = forms.CharField(
        max_length=255, required=False, label="AllowedIPs (override)",
        help_text="Blank = use the interface default (e.g. full tunnel).",
    )
    persistent_keepalive = forms.IntegerField(
        required=False, min_value=0, max_value=65535, label="PersistentKeepalive",
    )
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def clean_address(self):
        value = (self.cleaned_data.get("address") or "").strip()
        if value:
            try:
                ipaddress.ip_interface(value)
            except ValueError:
                raise forms.ValidationError(
                    "Enter a valid IP with CIDR, e.g. 10.8.0.2/32."
                )
        return value


class PeerEditForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Peer
        fields = [
            "name",
            "address",
            "enabled",
            "client_dns",
            "client_allowed_ips",
            "persistent_keepalive",
            "endpoint",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_address(self):
        value = (self.cleaned_data.get("address") or "").strip()
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ipaddress.ip_interface(part)
            except ValueError:
                raise forms.ValidationError(f"Invalid address: {part}")
        return value


class InterfaceForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = WGInterface
        fields = [
            "listen_port",
            "address",
            "endpoint_host",
            "dns",
            "mtu",
            "client_allowed_ips",
            "persistent_keepalive",
            "post_up",
            "post_down",
        ]
        widgets = {
            "post_up": forms.Textarea(attrs={"rows": 2}),
            "post_down": forms.Textarea(attrs={"rows": 2}),
        }

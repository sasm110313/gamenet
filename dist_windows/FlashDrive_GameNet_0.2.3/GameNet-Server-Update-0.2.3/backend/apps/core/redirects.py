from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def safe_redirect_next(request, fallback, *args, **kwargs):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ) and target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(fallback, *args, **kwargs)

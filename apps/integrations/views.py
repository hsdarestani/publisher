from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from apps.core.audit import log_event
from apps.publisher.forms import StoreAccountForm
from apps.publisher.models import StoreAccount
from .apple_store import AppleStoreClient
from .google_play import GooglePlayClient

@login_required
def account_list(request):
    return render(request, "integrations/account_list.html", {"accounts": StoreAccount.objects.all()})

@login_required
def account_create(request):
    form = StoreAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = form.save()
        log_event(request, "integration.create", f"Created {account}", account)
        messages.success(request, "Store account saved. Missing credentials will not affect the rest of the system.")
        return redirect("integration_accounts")
    return render(request, "shared/form.html", {"form": form, "title": "Add store account", "back_url": "/integrations/"})

@login_required
def account_edit(request, pk):
    account = get_object_or_404(StoreAccount, pk=pk)
    form = StoreAccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_event(request, "integration.update", f"Updated {account}", account)
        messages.success(request, "Store account updated.")
        return redirect("integration_accounts")
    return render(request, "shared/form.html", {"form": form, "title": f"Edit {account.name}", "back_url": "/integrations/"})

@login_required
def account_test(request, pk):
    account = get_object_or_404(StoreAccount, pk=pk)
    try:
        client = GooglePlayClient(account) if account.provider == "google" else AppleStoreClient(account)
        package = request.POST.get("package_name") or None
        result = client.test(package) if account.provider == "google" else client.test()
        account.status = "connected" if result.ok else "error"
        account.last_error = "" if result.ok else result.message
        account.last_tested_at = timezone.now()
        account.save(update_fields=["status", "last_error", "last_tested_at", "updated_at"])
        messages.success(request, result.message) if result.ok else messages.error(request, result.message)
    except Exception as exc:
        account.status, account.last_error, account.last_tested_at = "error", str(exc), timezone.now()
        account.save(update_fields=["status", "last_error", "last_tested_at", "updated_at"])
        messages.error(request, str(exc))
    return redirect("integration_accounts")

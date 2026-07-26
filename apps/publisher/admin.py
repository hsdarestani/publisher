from django.contrib import admin
from .models import StoreAccount, MobileApp, AppLocalization, AppAsset, Release, BuildAgent, Build, Job, Submission

for model in [StoreAccount, MobileApp, AppLocalization, AppAsset, Release, BuildAgent, Build, Job, Submission]:
    admin.site.register(model)

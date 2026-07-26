from django.conf import settings

def system_context(request):
    return {"PUBLIC_URL": settings.PUBLIC_URL, "PRODUCT_NAME": "A+ Publisher"}

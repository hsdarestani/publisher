import os,json
from pathlib import Path
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from django.core.files.base import ContentFile
from apps.publisher.models import MobileApp,AppAsset
from PIL import Image
app=MobileApp.objects.get(slug="be-different")
root=Path("/tmp/be-different-review7")
files=sorted(root.glob("*.png"))
assert files,"No captured screenshots found"
for source in files:
    name=source.name
    parts=name.split("--")
    assert len(parts)==4,name
    platform,locale,device,screen=parts
    with Image.open(source) as image:
        width,height=image.size
        rgb=image.convert("RGB")
        assert image.mode in ("RGB","RGBA"),image.mode
        assert width>=320 and height>=320
    asset,_=AppAsset.objects.get_or_create(app=app,kind="screenshot",platform=platform,locale=locale,device_type=device,sort_order=int(screen.split("-")[0]),defaults={"width":width,"height":height})
    asset.checksum=""
    asset.width=width;asset.height=height
    import io
    data=io.BytesIO();rgb.save(data,format="PNG")
    asset.file.save(name,ContentFile(data.getvalue()),save=True)
    source.unlink()
    print("CAPTURED_NATIVE_ASSET="+json.dumps({"platform":platform,"locale":locale,"device":device,"width":width,"height":height,"asset":asset.pk}))

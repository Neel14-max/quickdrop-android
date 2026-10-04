# QuickDrop Android app

## Get the APK (no Android Studio needed)
1. Create a free GitHub account and a new repository.
2. Upload ALL files of this folder (keep the `.github` folder).
3. Open the repo -> Actions tab -> "Build APK" -> wait ~4 minutes.
4. Open the finished run -> download artifact "QuickDrop-apk" -> unzip -> app-debug.apk.
5. Copy to the phone, open it, allow "install unknown apps" when asked.

## Or build locally
Open this folder in Android Studio and press Run (or Build > Build APK).

## Use
Laptop: pip install cryptography qrcode ; python quickdrop.py
Phone: open QuickDrop -> Scan QR code.
Received files on laptop: ./received   |   Files for phone: ./share
Files from laptop are saved on phone in Downloads/QuickDrop.

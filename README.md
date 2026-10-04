# QuickDrop
Fast, encrypted phone <-> laptop transfer over your phone hotspot. No internet, no cloud.

GitHub builds both apps (Actions tab -> latest run -> Artifacts):
- QuickDrop-Android-apk -> app-debug.apk  (phone)
- QuickDrop-Windows-exe -> QuickDrop.exe  (laptop)

First time: hotspot ON, PC joined to it, open QuickDrop.exe, in the phone app tap "Scan QR code".
After that: just open both apps - the phone finds the laptop by itself.

Laptop -> phone: drag files onto the QuickDrop window, or copy files and press Ctrl+V.
Phone -> laptop: in the app tap "Choose files", or use the phone's Share menu -> QuickDrop.
Tap a file in the phone app to download and open it.

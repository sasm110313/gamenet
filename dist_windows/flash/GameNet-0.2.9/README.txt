GameNet 0.2.9 — Client / Server / Cloud

نصب جدید:
- سرور سالن (Windows 10/11 x64): server-hub/GameNet-Server-0.2.9-Setup.exe
- کلاینت Windows 7 SP1 / سیستم ۳۲ بیتی: client/GameNet-0.2.9-win7-ia32.exe
- کلاینت Windows 10/11 x64: client/GameNet-0.2.9-win10-x64.exe

آپدیت نصب موجود (با دسترسی Administrator):
1. از دیتابیس و تنظیمات فعلی نسخه پشتیبان بگیرید.
2. ابر: bash cloud/deploy_cloud_update.sh cloud/gamenet-cloud-0.2.9.tar.gz
3. هاب: server-hub/GameNet-Server-Update-0.2.9.exe
4. کلاینت: client/GameNet-Client-Update-0.2.9.exe

فایل app.asar و latest.json برای آپدیت کلاینت، و ZIP سرور برای مسیر آپدیت خودکار هستند.
قفل موقت Alt+F5 نشست را حفظ می‌کند و هزینه طبق نشست جاری ادامه دارد.
سیاست PAUSE هزینه را هنگام قطعی متوقف می‌کند؛ CONTINUE آن را ادامه می‌دهد؛ AUTO_STOP پس از مهلت ۹۰ ثانیه تسویه می‌کند.

اعتبارسنجی:
- 17 تست رگرسیون Electron و بررسی TypeScript موفق.
- 73 تست منتخب بک‌اند شامل تست‌های جدید نشست/شبکه موفق؛ تست پیش‌فرض‌های قدیمی کسب‌وکار جداست.
- مجموعه قدیمی کامل سبز نیست (از جمله پیش‌فرض‌های اعتبار/تعرفه و سناریوهای ورود با موجودی صفر).
- اجرا و نصب واقعی روی ویندوز و بازی‌های DirectX/Vulkan در این محیط انجام نشده است.
- برای بررسی فایل‌ها: sha256sum -c SHA256SUMS.txt

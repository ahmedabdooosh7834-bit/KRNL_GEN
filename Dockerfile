# استخدام صورة Playwright الرسمية والمجهزة بكل اعتمادات المتصفحات على بايثون
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

# تعيين مسار العمل
WORKDIR /app

# نسخ وتثبيت متطلبات بايثون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت Chromium داخل الصورة
RUN playwright install chromium

# نسخ باقي ملفات المشروع
COPY . .

# المنفذ الافتراضي لـ Render
ENV PORT=8080
EXPOSE 8080

# تشغيل البوت
CMD ["python", "bot.py"]
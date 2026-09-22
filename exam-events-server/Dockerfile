FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py reset_password.py .
COPY public ./public
ENV DATA_DIR=/var/data PORT=8080 COOKIE_SECURE=true
EXPOSE 8080
CMD ["python", "server.py"]

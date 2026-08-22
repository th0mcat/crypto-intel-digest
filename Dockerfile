FROM python:3.12-slim

RUN useradd --create-home --shell /usr/sbin/nologin app
WORKDIR /home/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER app
CMD ["python", "-m", "app.main"]

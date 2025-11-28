FROM python:3.11.2
EXPOSE 80

ENV TZ="America/New_York"

RUN apt update -y
RUN apt install -y python3-venv git

RUN mkdir /app
RUN git clone https://github.com/johnatrootdynamics/carbook /app

WORKDIR /app
RUN pip3 install flask
CMD ["python3", "app.py"]

FROM python:3.11.2
EXPOSE 80

ENV TZ="America/New_York"

RUN apt update -y
RUN apt install -y python3-venv git

RUN mkdir /app
RUN git clone https://github.com/johnatrootdynamics/carbook /app

WORKDIR /app

# Create virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install dependencies
RUN echo "Listing directory during build:" && ls -al /app
# Start the app
CMD ["python3", "app.py"]

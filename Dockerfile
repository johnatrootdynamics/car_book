FROM python:3.11-slim

# Expose Flask port
EXPOSE 80

# Install needed system packages
RUN apt update -y && apt install -y python3-venv git

# Create app directory
RUN mkdir -p /app

# Clone the repository into /app
RUN git clone https://github.com/johnatrootdynamics/car_book /app

# Set working directory
WORKDIR /app

# Create virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install Python dependencies inside the virtual environment
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Run the application
CMD ["python", "app.py"]

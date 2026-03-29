// ============================================================
//  NEO — Minimal Sensor Firmware
//  Reads 3 physical sensors and sends CSV to Python server.
//
//  TX format (115200 baud, every 200 ms):
//    "light,temp_c,pressure_hpa,0.00,0.00,512,512,0,0\n"
//
//  Sensors:
//    LDR      A0        (photoresistor, raw 0-1023)
//    DHT11    pin 9     (temperature °C)
//    BMP180   I2C 0x77  (pressure hPa)
//
//  Required libraries (Arduino Library Manager):
//    Adafruit BMP085 Unified
//    DHT sensor library (Adafruit)
// ============================================================

#include <Wire.h>
#include <Adafruit_BMP085.h>
#include <DHT.h>

#define LDR_PIN   A0
#define DHT_PIN   9
#define DHT_TYPE  DHT11

Adafruit_BMP085 bmp;
DHT             dht(DHT_PIN, DHT_TYPE);

bool bmpOk = false;

void setup() {
    Serial.begin(115200);
    dht.begin();
    bmpOk = bmp.begin();
    delay(2000);   // DHT11 stabilise
}

void loop() {
    int   light    = analogRead(LDR_PIN);

    float temp_c   = dht.readTemperature();
    if (isnan(temp_c)) temp_c = 25.0;

    float pres_hpa = bmpOk ? bmp.readPressure() / 100.0 : 1013.25;
    if (pres_hpa < 800.0 || pres_hpa > 1100.0) pres_hpa = 1013.25;

    // CSV: light,temp_c,pressure_hpa,solar_ma,load_ma,pot1,pot2,tilt,button
    Serial.print(light);         Serial.print(',');
    Serial.print(temp_c,   1);   Serial.print(',');
    Serial.print(pres_hpa, 1);   Serial.print(',');
    Serial.print("0.00,0.00,512,512,0,0");
    Serial.println();

    delay(200);
}
